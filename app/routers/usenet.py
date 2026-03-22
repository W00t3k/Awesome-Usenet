from __future__ import annotations

import asyncio
import html as html_lib
import json
import logging
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

from fastapi import APIRouter, Query

from app import state
from app.config import limits, settings
from app.clients.usenet_client import UsenetClient
from app.clients.http_client import HTTPClient
from app.clients.poster_lookup_client import PosterLookupClient
from app.clients.rottentomatoes_client import RottenTomatoesClient
from app.services.usenet_parser import parse_release

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_release_title_year(raw_title: str) -> tuple[str, int | None]:
    compact = re.sub(r"[._]", " ", raw_title)
    compact = re.sub(
        r"\b(2160p|1080p|720p|x264|x265|h264|h265|hevc|hdr|webrip|web-dl|bluray|brrip|dvdrip|aac|dts|atmos|proper|repack|extended|criterion)\b",
        "", compact, flags=re.IGNORECASE,
    )
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", compact)
    year = int(year_match.group(1)) if year_match else None
    if year_match:
        title = compact[: year_match.start()].strip(" -:[]()")
    else:
        title = compact.strip()
    title = re.sub(r"\s+", " ", title).strip()
    return title or raw_title.strip(), year


def _normalize_released_at(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return None


def _release_sort_key(item: dict) -> tuple[int, int]:
    ts = item.get("released_at_iso")
    order = int(item.get("_order", 0))
    if not ts:
        return (0, order)
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (int(dt.timestamp()), order)
    except ValueError:
        return (0, order)


def _matches_usenet_query(item: dict, query: str) -> bool:
    q = query.strip().lower()
    if not q:
        return True
    blob = " ".join(
        str(part) for part in [
            item.get("title"), item.get("year"), item.get("indexer"),
            item.get("release_name"), item.get("where_url"),
        ] if part is not None
    ).lower()
    return q in blob


async def _enrich_usenet_posters(items: list[dict], max_items: int = 60) -> None:
    if not items:
        return
    poster_client = PosterLookupClient(
        timeout_seconds=settings.source_timeout_seconds,
        tmdb_api_key=settings.tmdb_api_key,
        memory_store=state.memory_store,
    )
    semaphore = asyncio.Semaphore(8)

    async def enrich(item: dict) -> None:
        async with semaphore:
            try:
                poster = await poster_client.poster_for(item["title"], item.get("year"))
            except Exception:
                return
            if poster:
                item["poster_url"] = poster

    await asyncio.gather(*(enrich(item) for item in items[:max_items]))


async def _crawl_usenet_releases(limit: int, query: str | None = None) -> dict:
    items: list[dict] = []
    errors: list[str] = []
    indexer_counts: dict[str, int] = {}

    def add_item(indexer: str, release_name: str, where_url: str | None = None,
                 released_at: str | None = None, details: str | None = None) -> None:
        title, year = _extract_release_title_year(release_name)
        released_at_iso = _normalize_released_at(released_at)
        items.append({
            "_order": len(items),
            "title": title, "year": year, "release_name": release_name,
            "indexer": indexer, "where_url": where_url,
            "released_at": released_at, "released_at_iso": released_at_iso, "details": details,
        })
        indexer_counts[indexer] = indexer_counts.get(indexer, 0) + 1

    _rss_url = settings.nzbgeek_rss_url or ""
    _rss_has_placeholder = "{API_KEY}" in _rss_url or "${API_KEY}" in _rss_url
    if _rss_url and (not _rss_has_placeholder or settings.nzbgeek_api_key):
        try:
            rows = await UsenetClient(
                base_url="https://api.nzbgeek.info",
                api_key=settings.nzbgeek_api_key or "",
                timeout_seconds=settings.source_timeout_seconds,
            ).movie_rss_feed(rss_url=settings.nzbgeek_rss_url, api_key=settings.nzbgeek_api_key)
            for row in rows:
                raw_title = str(row.get("title") or "").strip()
                if raw_title:
                    add_item("NZBGeek", raw_title, row.get("link"), row.get("pub_date"), row.get("description"))
        except Exception as exc:
            errors.append(f"NZBGeek: {exc}")

    if settings.drunkenslug_api_key:
        try:
            rows = await UsenetClient(
                base_url=settings.drunkenslug_base_url,
                api_key=settings.drunkenslug_api_key,
                timeout_seconds=settings.source_timeout_seconds,
            ).movie_search(query="")
            for row in rows:
                raw_title = str(row.get("title") or row.get("name") or "").strip()
                if raw_title:
                    add_item("DrunkenSlug", raw_title, row.get("link"),
                             row.get("pubDate") or row.get("pub_date"), row.get("description"))
        except Exception as exc:
            errors.append(f"DrunkenSlug: {exc}")

    if settings.usenet_api_key:
        try:
            rows = await UsenetClient(
                base_url=settings.usenet_base_url,
                api_key=settings.usenet_api_key,
                timeout_seconds=settings.source_timeout_seconds,
            ).movie_search(query="")
            for row in rows:
                raw_title = str(row.get("title") or row.get("name") or "").strip()
                if raw_title:
                    add_item("Usenet", raw_title, row.get("link"),
                             row.get("pubDate") or row.get("pub_date"), row.get("description"))
        except Exception as exc:
            errors.append(f"Usenet: {exc}")

    rt_scores: dict[str, int] = {}
    if settings.rottentomatoes_list_url:
        try:
            rows = await RottenTomatoesClient(settings.source_timeout_seconds).browse_movies(settings.rottentomatoes_list_url)
            for row in rows:
                title = row.get("title")
                score = row.get("tomatometer")
                if not title or not isinstance(score, int):
                    continue
                year = row.get("year") if isinstance(row.get("year"), int) else None
                key = f"{str(title).strip().lower()}::{year if year is not None else 'na'}"
                rt_scores[key] = score
        except Exception as exc:
            errors.append(f"RottenTomatoes: {exc}")

    for item in items:
        key_exact = f"{item['title'].strip().lower()}::{item['year'] if item.get('year') is not None else 'na'}"
        key_fallback = f"{item['title'].strip().lower()}::na"
        item["rottentomatoes_score"] = rt_scores.get(key_exact) or rt_scores.get(key_fallback)

    if query:
        items = [item for item in items if _matches_usenet_query(item, query)]

    await _enrich_usenet_posters(items, max_items=min(limit, 80))
    items.sort(key=lambda item: (-_release_sort_key(item)[0], _release_sort_key(item)[1]))
    public_rows = [
        {k: v for k, v in item.items() if not str(k).startswith("_")}
        for item in items[:limit]
    ]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_items": len(items),
        "indexers": indexer_counts,
        "errors": errors,
        "items": public_rows,
    }


async def query_usenet_sources(search_terms: str) -> dict[str, list[dict]]:
    """Used by chat router for usenet availability queries."""
    results: dict[str, list[dict]] = {}
    tasks = []

    if settings.nzbgeek_api_key or settings.nzbgeek_rss_url:
        async def _nzbgeek() -> None:
            try:
                rows = await UsenetClient(
                    base_url="https://api.nzbgeek.info",
                    api_key=settings.nzbgeek_api_key or "",
                    timeout_seconds=10.0,
                ).movie_search(query=search_terms, limit=5)
                results["nzbgeek"] = rows
            except Exception:
                results["nzbgeek"] = []
        tasks.append(_nzbgeek())

    if settings.drunkenslug_api_key:
        async def _drunkenslug() -> None:
            try:
                rows = await UsenetClient(
                    base_url=settings.drunkenslug_base_url or "https://drunkenslug.com/api",
                    api_key=settings.drunkenslug_api_key,
                    timeout_seconds=10.0,
                ).movie_search(query=search_terms, limit=5)
                results["drunkenslug"] = rows
            except Exception:
                results["drunkenslug"] = []
        tasks.append(_drunkenslug())

    if tasks:
        await asyncio.gather(*tasks)
    return results


def format_usenet_results(results: dict[str, list[dict]]) -> str:
    """Format usenet search results for LLM context."""
    lines = []
    for source, rows in results.items():
        if rows:
            lines.append(f"\n{source.upper()} ({len(rows)} results):")
            for row in rows[:3]:
                title = row.get("title", "Unknown")
                lines.append(f"  - {title}")
        else:
            lines.append(f"\n{source.upper()}: No results found")
    return "\n".join(lines)


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/api/usenet/releases")
async def get_usenet_releases(
    limit: int = Query(default=250, ge=1, le=limits.usenet_max),
    q: str | None = Query(default=None),
) -> dict:
    return await _crawl_usenet_releases(limit=limit, query=q)


@router.get("/api/usenet/latest")
async def get_usenet_latest(limit: int = Query(default=12, ge=1, le=50)) -> dict:
    """Get latest new movie releases from NZBGeek GeekSeek new_movies."""
    checked_at = datetime.now(UTC).isoformat()
    last_poll_row = state.memory_store.last_sync_job("usenet_poll")
    last_poll_at = (
        (last_poll_row.get("completed_at") or last_poll_row.get("started_at"))
        if last_poll_row else None
    )
    try:
        raw_movies = await _fetch_nzbgeek_movies(limit=limit * 3)
        feed_source = "nzbgeek_geekseek_new_movies"

        if not raw_movies:
            return {
                "ok": True, "releases": [], "count": 0, "checked_at": checked_at,
                "last_poll_at": last_poll_at, "poll_interval_minutes": settings.usenet_poll_interval_minutes,
                "feed_source": "nzbgeek_new_movies_unavailable",
            }

        _poster_client = None
        if settings.tmdb_api_key:
            _poster_client = PosterLookupClient(
                timeout_seconds=settings.source_timeout_seconds,
                tmdb_api_key=settings.tmdb_api_key,
                memory_store=state.memory_store,
            )

        parsed_movies = []
        seen_titles: set[str] = set()
        for r in raw_movies:
            raw_title = str(r.get("release_name") or r.get("title") or "").strip()
            if not raw_title:
                continue
            parsed = parse_release(raw_title)
            if parsed.is_tv_release:
                continue
            title = parsed.title.strip() or _extract_release_title_year(raw_title)[0]
            year = parsed.year
            if year is None:
                _title, fallback_year = _extract_release_title_year(raw_title)
                year = fallback_year
                if not title:
                    title = _title

            pub_date = str(r.get("pub_date") or r.get("released_at") or "").strip()
            has_release_markers = (
                parsed.quality != "unknown" or parsed.source != "unknown"
                or parsed.codec != "unknown" or year is not None
            )
            if not has_release_markers and not pub_date:
                continue
            title_key = title.lower()
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)

            poster_url = r.get("cover_url") or None
            overview = str(r.get("overview") or r.get("description") or r.get("details") or "").strip()
            official_release_date = str(r.get("official_release_date") or r.get("release_date") or "").strip()
            if overview:
                overview = re.sub(r"<[^>]+>", " ", overview)
                overview = re.sub(r"\s+", " ", overview).strip()

            parsed_movies.append({
                "title": title, "year": year, "poster_url": poster_url, "overview": overview,
                "official_release_date": official_release_date, "imdb_id": r.get("imdb_id") or None,
                "pub_date": pub_date, "raw_title": raw_title, "link": r.get("link"),
                "needs_tmdb": _poster_client and title and (not poster_url or not overview or not official_release_date),
            })
            if len(parsed_movies) >= limit:
                break

        async def enrich_movie(m: dict) -> None:
            if not m.get("needs_tmdb"):
                return
            try:
                info = await _poster_client.lookup(m["title"], m["year"])
                if info:
                    if not m["poster_url"]:
                        m["poster_url"] = info.get("poster_url")
                    tmdb_overview = str(info.get("overview") or "").strip()
                    if tmdb_overview:
                        m["overview"] = tmdb_overview
                    if not m["official_release_date"]:
                        m["official_release_date"] = str(info.get("release_date") or "").strip()
            except Exception:
                pass

        await asyncio.gather(*(enrich_movie(m) for m in parsed_movies))

        enriched = []
        for m in parsed_movies:
            overview = m["overview"]
            if len(overview) > 900:
                overview = f"{overview[:897].rstrip()}..."
            enriched.append({
                "title": m["title"], "year": m["year"], "poster_url": m["poster_url"],
                "overview": overview, "quality": "", "size": "", "source": "nzbgeek",
                "pub_date": m["pub_date"], "nzbgeek_found_at": m["pub_date"] or None,
                "official_release_date": m["official_release_date"] or None,
                "release_name": m["raw_title"], "imdb_id": m["imdb_id"], "link": m["link"],
            })

        return {
            "ok": True, "releases": enriched, "count": len(enriched),
            "checked_at": checked_at, "last_poll_at": last_poll_at,
            "poll_interval_minutes": settings.usenet_poll_interval_minutes, "feed_source": feed_source,
        }
    except Exception as exc:
        logger.warning(f"Failed to get latest usenet: {exc}")
        return {
            "ok": False, "releases": [], "error": str(exc),
            "checked_at": checked_at, "last_poll_at": last_poll_at,
            "poll_interval_minutes": settings.usenet_poll_interval_minutes,
        }


@router.get("/api/usenet/check")
async def check_usenet_availability(
    title: str = Query(...),
    year: int | None = Query(default=None),
) -> dict:
    api_key = settings.nzbgeek_api_key or ""
    if not api_key and settings.nzbgeek_rss_url:
        match = re.search(r'(?:apikey|r)=([^&]+)', settings.nzbgeek_rss_url)
        if match:
            api_key = match.group(1)
    if not api_key:
        return {"ok": False, "available": False, "message": "NZBGeek API key not configured"}
    try:
        client = UsenetClient(base_url="https://api.nzbgeek.info", api_key=api_key, timeout_seconds=settings.source_timeout_seconds)
        search_query = title.strip()
        if year:
            search_query = f"{search_query} {year}"
        rows = await client.movie_search(query=search_query, limit=60)
        if not rows and year:
            rows = await client.movie_search(query=title.strip(), limit=60)
        result_count = len(rows) if isinstance(rows, list) else 0
        return {"ok": True, "available": result_count > 0, "result_count": result_count,
                "title": title, "year": year, "checked_at": datetime.now(UTC).isoformat()}
    except Exception as exc:
        return {"ok": False, "available": False, "message": str(exc)}


@router.get("/api/releases/{title}")
async def get_releases_for_movie(title: str, year: int | None = Query(default=None)) -> dict:
    """Get available usenet releases for a movie with quality options."""
    from app.services.usenet_parser import parse_release_with_metadata, release_to_dict

    search_query = title.strip()
    if year:
        search_query = f"{search_query} {year}"

    releases: list[dict] = []
    errors: list[str] = []

    if settings.nzbgeek_api_key:
        try:
            results = await UsenetClient(
                base_url="https://api.nzbgeek.info", api_key=settings.nzbgeek_api_key,
                timeout_seconds=settings.source_timeout_seconds,
            ).movie_search(query=search_query, limit=50)
            for item in results:
                raw_title = item.get("title", "")
                if not raw_title:
                    continue
                parsed = parse_release_with_metadata(
                    raw_title=raw_title, size_bytes=item.get("size_bytes"),
                    size_human=item.get("size_human"), link=item.get("link"), indexer="nzbgeek",
                )
                if parsed.is_tv_release:
                    continue
                if year and parsed.year and parsed.year != year:
                    continue
                releases.append(release_to_dict(parsed))
        except Exception as exc:
            errors.append(f"NZBGeek: {exc}")

    if settings.drunkenslug_api_key:
        try:
            results = await UsenetClient(
                base_url=settings.drunkenslug_base_url or "https://drunkenslug.com/api",
                api_key=settings.drunkenslug_api_key,
                timeout_seconds=settings.source_timeout_seconds,
            ).movie_search(query=search_query, limit=50)
            for item in results:
                raw_title = item.get("title", "")
                if not raw_title:
                    continue
                parsed = parse_release_with_metadata(
                    raw_title=raw_title, size_bytes=item.get("size_bytes"),
                    size_human=item.get("size_human"), link=item.get("link"), indexer="drunkenslug",
                )
                if parsed.is_tv_release:
                    continue
                if year and parsed.year and parsed.year != year:
                    continue
                releases.append(release_to_dict(parsed))
        except Exception as exc:
            errors.append(f"DrunkenSlug: {exc}")

    releases.sort(key=lambda r: r.get("score", 0), reverse=True)
    seen_titles: set[str] = set()
    unique_releases = []
    for release in releases:
        raw = release.get("raw_title", "")
        if raw not in seen_titles:
            seen_titles.add(raw)
            unique_releases.append(release)

    return {
        "ok": True, "title": title, "year": year,
        "releases": unique_releases[:30], "total_found": len(unique_releases),
        "errors": errors if errors else None,
    }


async def _fetch_nzbgeek_movies(limit: int = 100) -> list[dict]:
    """Fetch new movie releases from NZBGeek GeekSeek new_movies page."""

    def parse_geekseek_payload(raw: str, max_items: int) -> list[dict]:
        text = (raw or "").strip()
        if not text:
            return []
        lowered = text.lower()
        if "<rss" in lowered and "<item" in lowered:
            try:
                return UsenetClient._parse_rss_items(text)[:max_items]
            except Exception:
                pass

        rows: list[dict] = []
        seen_links: set[str] = set()
        seen_titles: set[str] = set()

        def add_row(*, title: str, link: str | None, pub_date: str | None = None,
                    description: str | None = None, cover_url: str | None = None, imdb_id: str | None = None) -> None:
            cleaned_title = re.sub(r"\s+", " ", (title or "")).strip()
            if not cleaned_title:
                return
            title_key = cleaned_title.casefold()
            link_key = (link or "").strip()
            if title_key in seen_titles or (link_key and link_key in seen_links):
                return
            seen_titles.add(title_key)
            if link_key:
                seen_links.add(link_key)
            rows.append({"title": cleaned_title, "link": link_key or None, "pub_date": (pub_date or "").strip() or None,
                         "description": (description or "").strip() or None, "cover_url": (cover_url or "").strip() or None,
                         "imdb_id": (imdb_id or "").strip() or None})

        date_re = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|[A-Z][a-z]{2,9}\s+\d{1,2},\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})\b")
        imdb_re = re.compile(r"(tt\d{6,10})")

        def parse_with_regex() -> None:
            anchor_re = re.compile(r"<a[^>]*href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<body>.*?)</a>", re.IGNORECASE | re.DOTALL)
            title_attr_re = re.compile(r"title=[\"'](?P<title>[^\"']+)[\"']", re.IGNORECASE)
            tag_re = re.compile(r"<[^>]+>")
            img_re = re.compile(r"<img[^>]*(?:data-src|src)=[\"'](?P<src>[^\"']+)[\"'][^>]*>", re.IGNORECASE | re.DOTALL)
            for match in anchor_re.finditer(text):
                href = str(match.group("href") or "").strip()
                href_lower = href.lower()
                if "/details/" not in href_lower and "t=get" not in href_lower:
                    continue
                full_anchor = match.group(0) or ""
                title_match = title_attr_re.search(full_anchor)
                raw_title = str(title_match.group("title") if title_match else "").strip()
                if not raw_title:
                    body_text = tag_re.sub(" ", match.group("body") or "")
                    raw_title = re.sub(r"\s+", " ", html_lib.unescape(body_text)).strip()
                if not raw_title or raw_title.casefold() in {"download", "download nzb", "get nzb"}:
                    continue
                start, end = max(0, match.start() - 800), min(len(text), match.end() + 800)
                context = text[start:end]
                context_plain = re.sub(r"\s+", " ", html_lib.unescape(tag_re.sub(" ", context))).strip()
                pub_date_match = date_re.search(context_plain)
                pub_date = pub_date_match.group(0) if pub_date_match else None
                imdb_match = imdb_re.search(context)
                image_match = img_re.search(context)
                cover_url = image_match.group("src").strip() if image_match else None
                if cover_url:
                    cover_url = urljoin("https://nzbgeek.info", cover_url)
                add_row(title=html_lib.unescape(raw_title), link=urljoin("https://nzbgeek.info", href),
                        pub_date=pub_date, description=context_plain, cover_url=cover_url,
                        imdb_id=imdb_match.group(1) if imdb_match else None)
                if len(rows) >= max_items:
                    break

        try:
            from bs4 import BeautifulSoup
        except Exception:
            parse_with_regex()
            return rows[:max_items]

        soup = BeautifulSoup(text, "html.parser")
        for anchor in soup.select("a[href]"):
            href = str(anchor.get("href") or "").strip()
            if not href or ("/details/" not in href.lower() and "t=get" not in href.lower()):
                continue
            container = anchor.find_parent(["article", "li", "tr", "div"]) or anchor
            raw_title = (str(anchor.get("title") or "").strip() or
                         str(container.get("data-title") or "").strip() or
                         anchor.get_text(" ", strip=True))
            if not raw_title or raw_title.casefold() in {"download", "download nzb", "get nzb"}:
                continue
            context_text = container.get_text(" ", strip=True)
            pub_date_match = date_re.search(context_text or "")
            pub_date = pub_date_match.group(0) if pub_date_match else None
            img = container.find("img")
            cover_url = None
            if img is not None:
                cover_url = str(img.get("data-src") or img.get("src") or "").strip() or None
                if cover_url:
                    cover_url = urljoin("https://nzbgeek.info", cover_url)
            imdb_id = None
            imdb_link = container.find("a", href=re.compile(r"imdb\.com/title/tt\d{6,10}", re.IGNORECASE))
            if imdb_link:
                match = imdb_re.search(str(imdb_link.get("href") or ""))
                if match:
                    imdb_id = match.group(1)
            add_row(title=raw_title, link=urljoin("https://nzbgeek.info", href),
                    pub_date=pub_date, description=context_text, cover_url=cover_url, imdb_id=imdb_id)
            if len(rows) >= max_items:
                break

        if len(rows) < max_items:
            for script in soup.select("script[type='application/ld+json'], script"):
                script_text = (script.string or script.get_text() or "").strip()
                if not script_text or ("new_movies" not in script_text and "itemListElement" not in script_text):
                    continue
                try:
                    payload = json.loads(script_text)
                except Exception:
                    continue
                objects = payload if isinstance(payload, list) else [payload]
                for obj in objects:
                    if not isinstance(obj, dict):
                        continue
                    items_list = obj.get("itemListElement")
                    if not isinstance(items_list, list):
                        continue
                    for item in items_list:
                        if not isinstance(item, dict):
                            continue
                        target = item.get("item") if isinstance(item.get("item"), dict) else item
                        title = str(target.get("name") or target.get("title") or "").strip()
                        if not title:
                            continue
                        add_row(title=title, link=target.get("url"),
                                pub_date=target.get("datePublished") or target.get("dateCreated"),
                                description=target.get("description"), cover_url=target.get("image"), imdb_id=None)
                        if len(rows) >= max_items:
                            break
                    if len(rows) >= max_items:
                        break
                if len(rows) >= max_items:
                    break

        if not rows:
            parse_with_regex()
        return rows[:max_items]

    api_key = settings.nzbgeek_api_key or ""
    if not api_key and settings.nzbgeek_rss_url:
        match = re.search(r'(?:apikey|r)=([^&]+)', settings.nzbgeek_rss_url)
        if match:
            api_key = match.group(1)
    if not api_key:
        return []

    async def fetch_new_movies_rss() -> list[dict]:
        client = UsenetClient(base_url="https://api.nzbgeek.info", api_key=api_key, timeout_seconds=settings.source_timeout_seconds)
        movies_url = f"https://api.nzbgeek.info/rss?t=new_movies&limit={limit}&r={api_key}"
        return await client.movie_rss_feed(rss_url=movies_url, api_key=api_key)

    try:
        http = HTTPClient(timeout_seconds=settings.source_timeout_seconds)
        raw_payload = await http.get_text(
            "https://nzbgeek.info/geekseek.php",
            params={"new_movies": "", "r": api_key, "apikey": api_key},
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        rows = parse_geekseek_payload(raw_payload, max_items=limit * 3)
        if rows:
            def parse_date(item: dict) -> float:
                pd = item.get("pub_date") or ""
                try:
                    return parsedate_to_datetime(str(pd)).timestamp()
                except Exception:
                    return 0.0
            rows.sort(key=parse_date, reverse=True)
            return rows[:limit]
        return await fetch_new_movies_rss()
    except Exception as exc:
        logger.warning(f"Failed to fetch NZBGeek GeekSeek new_movies: {exc}")
        try:
            return await fetch_new_movies_rss()
        except Exception as rss_exc:
            logger.warning(f"NZBGeek new_movies RSS fallback failed: {rss_exc}")
            return []
