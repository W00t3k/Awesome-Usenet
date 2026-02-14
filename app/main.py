from __future__ import annotations

import asyncio
import re
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv, set_key
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from app.agents.criterion_agent import CriterionAgent
from app.agents.drunkenslug_agent import DrunkenSlugAgent
from app.agents.oscar_agent import OscarAgent
from app.agents.plex_agent import PlexAgent
from app.agents.preference_agent import PreferenceAgent
from app.agents.radarr_agent import RadarrAgent
from app.agents.rogerebert_agent import RogerEbertAgent
from app.agents.releases_agent import ReleasesAgent
from app.agents.rottentomatoes_agent import RottenTomatoesAgent
from app.agents.upcoming_agent import UpcomingAgent
from app.agents.usenet_agent import UsenetAgent
from app.clients.plex_client import PlexClient
from app.clients.poster_lookup_client import PosterLookupClient
from app.clients.radarr_client import RadarrClient
from app.clients.rogerebert_client import RogerEbertClient
from app.clients.releases_client import ReleasesClient
from app.clients.rottentomatoes_client import RottenTomatoesClient
from app.clients.tmdb_client import TMDBClient
from app.clients.usenet_client import UsenetClient
from app.config import settings
from app.models import (
    FeedbackInput,
    FeedbackRow,
    MovieCandidate,
    RecommendationResponse,
    SeenMovieDeleteInput,
    SeenMovieInput,
    SeenMovieRow,
)
from app.services.embedding import EmbeddingService
from app.services.memory_store import MemoryStore
from app.services.recommender import Recommender
from app.services.swarm import SwarmOrchestrator

base_dir = Path(__file__).resolve().parent
project_root = base_dir.parent
env_path = project_root / ".env"
env_example_path = project_root / ".env.example"

load_dotenv(dotenv_path=env_path)


DEFAULT_URLS: dict[str, str] = {
    "rottentomatoes_list_url": "https://www.rottentomatoes.com/browse/movies_at_home/sort:popular",
    "releases_url": "https://www.releases.com/calendar/movies/upcoming",
    "rogerebert_reviews_url": "https://www.rogerebert.com/reviews",
    "plex_base_url": "http://localhost:32400",
    "radarr_base_url": "http://localhost:7878",
    "nzbgeek_rss_url": "https://api.nzbgeek.info/rss?t=search&cat=2000&apikey={API_KEY}",
    "drunkenslug_base_url": "https://drunkenslug.com/api",
    "usenet_base_url": "http://localhost:5076",
}

REQUIRED_URL_FIELDS = {"plex_base_url", "radarr_base_url", "drunkenslug_base_url", "usenet_base_url"}

ENV_KEY_MAP: dict[str, str] = {
    "tmdb_api_key": "TMDB_API_KEY",
    "rottentomatoes_list_url": "ROTTENTOMATOES_LIST_URL",
    "releases_url": "RELEASES_URL",
    "rogerebert_reviews_url": "ROGEREBERT_REVIEWS_URL",
    "plex_base_url": "PLEX_BASE_URL",
    "plex_token": "PLEX_TOKEN",
    "radarr_base_url": "RADARR_BASE_URL",
    "radarr_api_key": "RADARR_API_KEY",
    "nzbgeek_rss_url": "NZBGEEK_RSS_URL",
    "nzbgeek_api_key": "NZBGEEK_API_KEY",
    "drunkenslug_base_url": "DRUNKENSLUG_BASE_URL",
    "drunkenslug_api_key": "DRUNKENSLUG_API_KEY",
    "usenet_base_url": "USENET_BASE_URL",
    "usenet_api_key": "USENET_API_KEY",
}

OPTIONAL_FIELDS = {
    "tmdb_api_key",
    "rottentomatoes_list_url",
    "releases_url",
    "rogerebert_reviews_url",
    "plex_token",
    "radarr_api_key",
    "nzbgeek_rss_url",
    "nzbgeek_api_key",
    "drunkenslug_api_key",
    "usenet_api_key",
}


class IntegrationSettingsPayload(BaseModel):
    tmdb_api_key: str | None = None
    rottentomatoes_list_url: str | None = None
    releases_url: str | None = None
    rogerebert_reviews_url: str | None = None
    plex_base_url: str | None = None
    plex_token: str | None = None
    radarr_base_url: str | None = None
    radarr_api_key: str | None = None
    nzbgeek_rss_url: str | None = None
    nzbgeek_api_key: str | None = None
    drunkenslug_base_url: str | None = None
    drunkenslug_api_key: str | None = None
    usenet_base_url: str | None = None
    usenet_api_key: str | None = None


class IntegrationTestRequest(BaseModel):
    integration: Literal[
        "tmdb",
        "rottentomatoes",
        "releases",
        "rogerebert",
        "plex",
        "radarr",
        "nzbgeek",
        "drunkenslug",
        "usenet",
    ]
    values: IntegrationSettingsPayload | None = None


class DownloadHistoryClearRequest(BaseModel):
    auto_download: bool = True
    auto_delete: bool = True
    limit: int = 80


class DownloadCancelRequest(BaseModel):
    queue_id: int
    remove_from_client: bool = True
    blocklist: bool = False


class UsenetDownloadItem(BaseModel):
    title: str
    year: int | None = None


class UsenetDownloadBulkRequest(BaseModel):
    items: list[UsenetDownloadItem]


def _ensure_env_file() -> None:
    if env_path.exists():
        return
    if env_example_path.exists():
        env_path.write_text(env_example_path.read_text())
    else:
        env_path.write_text("")


def _to_public_settings_values() -> dict[str, str]:
    return {
        "tmdb_api_key": settings.tmdb_api_key or "",
        "rottentomatoes_list_url": settings.rottentomatoes_list_url or "",
        "releases_url": settings.releases_url or "",
        "rogerebert_reviews_url": settings.rogerebert_reviews_url or "",
        "plex_base_url": settings.plex_base_url or DEFAULT_URLS["plex_base_url"],
        "plex_token": settings.plex_token or "",
        "radarr_base_url": settings.radarr_base_url or DEFAULT_URLS["radarr_base_url"],
        "radarr_api_key": settings.radarr_api_key or "",
        "nzbgeek_rss_url": settings.nzbgeek_rss_url or "",
        "nzbgeek_api_key": settings.nzbgeek_api_key or "",
        "drunkenslug_base_url": settings.drunkenslug_base_url or DEFAULT_URLS["drunkenslug_base_url"],
        "drunkenslug_api_key": settings.drunkenslug_api_key or "",
        "usenet_base_url": settings.usenet_base_url or DEFAULT_URLS["usenet_base_url"],
        "usenet_api_key": settings.usenet_api_key or "",
    }


def _effective_settings_values(overrides: dict[str, str | None] | None = None) -> dict[str, str]:
    values = _to_public_settings_values()
    if not overrides:
        return values

    for field_name, raw_value in overrides.items():
        if field_name not in ENV_KEY_MAP:
            continue
        value = (raw_value or "").strip()
        if field_name in REQUIRED_URL_FIELDS and value == "":
            value = DEFAULT_URLS[field_name]
        values[field_name] = value

    return values


def _set_setting_value(field_name: str, value: str) -> None:
    if field_name in OPTIONAL_FIELDS and value == "":
        setattr(settings, field_name, None)
        return
    setattr(settings, field_name, value)


def _save_settings(payload: dict[str, str | None]) -> None:
    _ensure_env_file()
    for field_name, raw_value in payload.items():
        if field_name not in ENV_KEY_MAP:
            continue
        value = (raw_value or "").strip()

        if field_name in REQUIRED_URL_FIELDS and value == "":
            value = DEFAULT_URLS[field_name]

        set_key(str(env_path), ENV_KEY_MAP[field_name], value, quote_mode="never")
        _set_setting_value(field_name, value)

    load_dotenv(dotenv_path=env_path, override=True)


def _build_runtime() -> tuple[MemoryStore, SwarmOrchestrator]:
    embedding_service = EmbeddingService()
    memory_store = MemoryStore(
        db_path=project_root / settings.memory_db_path,
        embedding_service=embedding_service,
    )

    agents = [
        OscarAgent(dataset_path=project_root / "data/oscars_best_picture.json"),
        CriterionAgent(dataset_path=project_root / "data/criterion_collection.json"),
        UpcomingAgent(
            tmdb_api_key=settings.tmdb_api_key,
            timeout_seconds=settings.source_timeout_seconds,
            fallback_dataset_path=project_root / "data/upcoming_seed.json",
        ),
        RottenTomatoesAgent(
            list_url=settings.rottentomatoes_list_url,
            timeout_seconds=settings.source_timeout_seconds,
            fallback_dataset_path=project_root / "data/rottentomatoes_seed.json",
        ),
        ReleasesAgent(
            releases_url=settings.releases_url,
            timeout_seconds=settings.source_timeout_seconds,
            fallback_dataset_path=project_root / "data/releases_seed.json",
        ),
        RogerEbertAgent(
            reviews_url=settings.rogerebert_reviews_url,
            timeout_seconds=settings.source_timeout_seconds,
            fallback_dataset_path=project_root / "data/rogerebert_seed.json",
        ),
        PlexAgent(
            base_url=settings.plex_base_url,
            token=settings.plex_token,
            timeout_seconds=settings.source_timeout_seconds,
        ),
        RadarrAgent(
            base_url=settings.radarr_base_url,
            api_key=settings.radarr_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        ),
        UsenetAgent(
            rss_url=settings.nzbgeek_rss_url,
            api_key=settings.nzbgeek_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        ),
        DrunkenSlugAgent(
            base_url=settings.drunkenslug_base_url,
            api_key=settings.drunkenslug_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        ),
        PreferenceAgent(memory_store=memory_store),
    ]

    recommender = Recommender(memory_store=memory_store)
    poster_lookup_client = PosterLookupClient(
        timeout_seconds=settings.source_timeout_seconds,
        tmdb_api_key=settings.tmdb_api_key,
    )
    tmdb_client = (
        TMDBClient(api_key=settings.tmdb_api_key, timeout_seconds=settings.source_timeout_seconds)
        if settings.tmdb_api_key
        else None
    )
    swarm = SwarmOrchestrator(
        agents=agents,
        recommender=recommender,
        poster_lookup_client=poster_lookup_client,
        tmdb_client=tmdb_client,
    )
    return memory_store, swarm


app = FastAPI(title=settings.app_title)
templates = Jinja2Templates(directory=str(base_dir / "templates"))
app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")

runtime_lock = asyncio.Lock()
memory_store, swarm = _build_runtime()


async def _reload_runtime() -> None:
    global memory_store, swarm
    async with runtime_lock:
        memory_store, swarm = _build_runtime()


async def _integration_status() -> dict[str, bool]:
    nzbgeek_configured = bool(settings.nzbgeek_rss_url) and (
        ("{API_KEY}" not in (settings.nzbgeek_rss_url or "") and "${API_KEY}" not in (settings.nzbgeek_rss_url or ""))
        or bool(settings.nzbgeek_api_key)
    )
    return {
        "tmdb": bool(settings.tmdb_api_key),
        "rottentomatoes": bool(settings.rottentomatoes_list_url),
        "releases": bool(settings.releases_url),
        "rogerebert": bool(settings.rogerebert_reviews_url),
        "plex": bool(settings.plex_token),
        "radarr": bool(settings.radarr_api_key),
        "nzbgeek": nzbgeek_configured,
        "drunkenslug": bool(settings.drunkenslug_api_key),
        "usenet": bool(settings.usenet_api_key or settings.nzbgeek_api_key or settings.drunkenslug_api_key),
    }


def _parse_sources_query(raw_sources: str | None) -> set[str] | None:
    if not raw_sources:
        return None
    parts = {part.strip().lower() for part in raw_sources.split(",") if part.strip()}
    return parts or None


def _normalize_release_date(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        if "T" in value:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None


def _parse_date_query(raw: str | None) -> date | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _movie_source_keys(movie: MovieCandidate, agent_name: str) -> set[str]:
    tags = {tag.lower() for tag in movie.source_tags}
    keys = set(tags)
    keys.add(agent_name.lower())

    if any(tag.startswith("rt-") for tag in tags) or "rottentomatoes" in tags:
        keys.add("rt")
        keys.add("rottentomatoes")
    if "nzbgeek-rss" in tags:
        keys.add("nzbgeek")
    if "drunkenslug" in tags:
        keys.add("drunkenslug")
    if movie.available_on_usenet:
        keys.add("usenet")
    if movie.available_on_plex:
        keys.add("plex")
    if movie.available_on_radarr:
        keys.add("radarr")
    return keys


def _build_release_calendar(
    source_movies: dict[str, list[MovieCandidate]],
    required_sources: set[str] | None = None,
    release_date_from: date | None = None,
    release_date_to: date | None = None,
) -> list[dict]:
    merged: dict[str, dict] = {}
    for agent_name, movies in source_movies.items():
        for movie in movies:
            release_date = _normalize_release_date(movie.release_date)
            if not release_date:
                continue
            release_day = _parse_date_query(release_date)
            if release_day is None:
                continue
            if release_date_from is not None and release_day < release_date_from:
                continue
            if release_date_to is not None and release_day > release_date_to:
                continue

            source_keys = _movie_source_keys(movie, agent_name)
            if required_sources and source_keys.isdisjoint(required_sources):
                continue

            key = f"{movie.title.strip().lower()}::{movie.year if movie.year is not None else 'na'}::{release_date}"
            if key not in merged:
                merged[key] = {
                    "title": movie.title,
                    "year": movie.year,
                    "release_date": release_date,
                    "poster_url": movie.poster_url,
                    "sources": set(source_keys),
                }
            else:
                existing = merged[key]
                existing["sources"] = existing["sources"].union(source_keys)
                if not existing.get("poster_url") and movie.poster_url:
                    existing["poster_url"] = movie.poster_url

    rows = []
    for row in merged.values():
        rows.append(
            {
                "title": row["title"],
                "year": row["year"],
                "release_date": row["release_date"],
                "poster_url": row["poster_url"],
                "sources": sorted(row["sources"]),
            }
        )
    rows.sort(key=lambda item: (item["release_date"], item["title"].lower()))
    return rows


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time_left_seconds(value: str | None) -> int | None:
    if not value:
        return None
    parts = [part for part in value.strip().split(":") if part != ""]
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = [int(part) for part in parts]
    except ValueError:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _human_bytes(value: float | None) -> str | None:
    if value is None:
        return None
    size = float(value)
    if size < 0:
        size = 0
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    return f"{size:.1f} {units[idx]}"


def _build_download_health_payload(queue_rows: list[dict]) -> dict:
    items: list[dict] = []
    total_rate = 0.0

    for row in queue_rows:
        movie = row.get("movie") if isinstance(row.get("movie"), dict) else {}
        title = str(movie.get("title") or row.get("title") or "Unknown title")
        year = movie.get("year")
        status = str(
            row.get("status")
            or row.get("trackedDownloadStatus")
            or row.get("trackedDownloadState")
            or "unknown"
        )
        time_left = str(row.get("timeleft") or row.get("timeLeft") or "").strip() or None

        size_left = _as_float(row.get("sizeleft") or row.get("sizeLeft"))
        total_size = _as_float(row.get("size") or row.get("sizeBytes"))
        rate = _as_float(row.get("downloadClientRate") or row.get("downloadRate") or row.get("rate"))
        if rate is None and size_left is not None and time_left:
            secs = _parse_time_left_seconds(time_left)
            if secs and secs > 0:
                rate = size_left / secs

        if rate is not None and rate > 0:
            total_rate += rate

        progress = None
        if total_size and size_left is not None and total_size > 0:
            progress = max(0.0, min(100.0, ((total_size - size_left) / total_size) * 100.0))

        queue_id = row.get("id")
        try:
            queue_id = int(queue_id) if queue_id is not None else None
        except (TypeError, ValueError):
            queue_id = None

        movie_id = movie.get("id") or row.get("movieId")
        try:
            movie_id = int(movie_id) if movie_id is not None else None
        except (TypeError, ValueError):
            movie_id = None

        items.append(
            {
                "queue_id": queue_id,
                "movie_id": movie_id,
                "title": title,
                "year": year if isinstance(year, int) else None,
                "status": status,
                "time_left": time_left,
                "progress": round(progress, 1) if progress is not None else None,
                "size_left_human": _human_bytes(size_left),
                "total_size_human": _human_bytes(total_size),
                "rate_human": f"{_human_bytes(rate)}/s" if rate is not None else None,
            }
        )

    active = [
        item
        for item in items
        if any(
            token in item["status"].lower()
            for token in ("downloading", "queued", "delay", "pending", "paused")
        )
    ]
    if not active:
        active = items

    return {
        "queue_count": len(items),
        "active_count": len(active),
        "download_rate_human": f"{_human_bytes(total_rate)}/s" if total_rate > 0 else None,
        "items": active[:25],
    }


def _build_download_history_payload(rows: list[dict], limit: int) -> list[dict]:
    history: list[dict] = []
    for row in rows[:limit]:
        movie = row.get("movie") if isinstance(row.get("movie"), dict) else {}
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        history.append(
            {
                "title": str(movie.get("title") or row.get("sourceTitle") or "Unknown title"),
                "year": movie.get("year") if isinstance(movie.get("year"), int) else None,
                "event": str(row.get("eventType") or "unknown"),
                "timestamp": row.get("date"),
                "download_client": data.get("downloadClient") or data.get("downloadClientName"),
                "source_title": row.get("sourceTitle"),
                "quality": (
                    ((row.get("quality") or {}).get("quality") or {}).get("name")
                    if isinstance(row.get("quality"), dict)
                    else None
                ),
            }
        )
    return history


def _extract_release_title_year(raw_title: str) -> tuple[str, int | None]:
    compact = re.sub(r"[._]", " ", raw_title)
    compact = re.sub(
        r"\b(2160p|1080p|720p|x264|x265|h264|h265|hevc|hdr|webrip|web-dl|bluray|brrip|dvdrip|aac|dts|atmos|proper|repack|extended|criterion)\b",
        "",
        compact,
        flags=re.IGNORECASE,
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
        str(part)
        for part in [
            item.get("title"),
            item.get("year"),
            item.get("indexer"),
            item.get("release_name"),
            item.get("where_url"),
        ]
        if part is not None
    ).lower()
    return q in blob


async def _enrich_usenet_posters(items: list[dict], max_items: int = 60) -> None:
    if not items:
        return
    poster_client = PosterLookupClient(
        timeout_seconds=settings.source_timeout_seconds,
        tmdb_api_key=settings.tmdb_api_key,
    )
    semaphore = asyncio.Semaphore(8)

    async def enrich(item: dict) -> None:
        async with semaphore:
            try:
                poster = await poster_client.poster_for(item["title"], item.get("year"))
            except Exception:  # noqa: BLE001
                return
            if poster:
                item["poster_url"] = poster

    await asyncio.gather(*(enrich(item) for item in items[:max_items]))


async def _crawl_usenet_releases(limit: int, query: str | None = None) -> dict:
    items: list[dict] = []
    errors: list[str] = []
    indexer_counts: dict[str, int] = {}

    def add_item(
        indexer: str,
        release_name: str,
        where_url: str | None = None,
        released_at: str | None = None,
        details: str | None = None,
    ) -> None:
        title, year = _extract_release_title_year(release_name)
        released_at_iso = _normalize_released_at(released_at)
        items.append(
            {
                "_order": len(items),
                "title": title,
                "year": year,
                "release_name": release_name,
                "indexer": indexer,
                "where_url": where_url,
                "released_at": released_at,
                "released_at_iso": released_at_iso,
                "details": details,
            }
        )
        indexer_counts[indexer] = indexer_counts.get(indexer, 0) + 1

    if settings.nzbgeek_rss_url and (
        ("{API_KEY}" not in settings.nzbgeek_rss_url and "${API_KEY}" not in settings.nzbgeek_rss_url)
        or settings.nzbgeek_api_key
    ):
        try:
            rows = await UsenetClient(
                base_url="https://api.nzbgeek.info",
                api_key=settings.nzbgeek_api_key or "",
                timeout_seconds=settings.source_timeout_seconds,
            ).movie_rss_feed(
                rss_url=settings.nzbgeek_rss_url,
                api_key=settings.nzbgeek_api_key,
            )
            for row in rows:
                raw_title = str(row.get("title") or "").strip()
                if not raw_title:
                    continue
                add_item(
                    indexer="NZBGeek",
                    release_name=raw_title,
                    where_url=row.get("link"),
                    released_at=row.get("pub_date"),
                    details=row.get("description"),
                )
        except Exception as exc:  # noqa: BLE001
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
                if not raw_title:
                    continue
                add_item(
                    indexer="DrunkenSlug",
                    release_name=raw_title,
                    where_url=row.get("link"),
                    released_at=row.get("pubDate") or row.get("pub_date"),
                    details=row.get("description"),
                )
        except Exception as exc:  # noqa: BLE001
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
                if not raw_title:
                    continue
                add_item(
                    indexer="Usenet",
                    release_name=raw_title,
                    where_url=row.get("link"),
                    released_at=row.get("pubDate") or row.get("pub_date"),
                    details=row.get("description"),
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Usenet: {exc}")

    rt_scores: dict[str, int] = {}
    if settings.rottentomatoes_list_url:
        try:
            rows = await RottenTomatoesClient(settings.source_timeout_seconds).browse_movies(
                settings.rottentomatoes_list_url
            )
            for row in rows:
                title = row.get("title")
                score = row.get("tomatometer")
                if not title or not isinstance(score, int):
                    continue
                year = row.get("year") if isinstance(row.get("year"), int) else None
                key = f"{str(title).strip().lower()}::{year if year is not None else 'na'}"
                rt_scores[key] = score
        except Exception as exc:  # noqa: BLE001
            errors.append(f"RottenTomatoes: {exc}")

    for item in items:
        key_exact = f"{item['title'].strip().lower()}::{item['year'] if item.get('year') is not None else 'na'}"
        key_fallback = f"{item['title'].strip().lower()}::na"
        score = rt_scores.get(key_exact)
        if score is None:
            score = rt_scores.get(key_fallback)
        item["rottentomatoes_score"] = score

    if query:
        items = [item for item in items if _matches_usenet_query(item, query)]

    await _enrich_usenet_posters(items, max_items=min(limit, 80))
    items.sort(key=lambda item: (-_release_sort_key(item)[0], _release_sort_key(item)[1]))
    public_rows = [
        {key: value for key, value in item.items() if not str(key).startswith("_")}
        for item in items[:limit]
    ]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_items": len(items),
        "indexers": indexer_counts,
        "errors": errors,
        "items": public_rows,
    }


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"app_title": settings.app_title},
    )


@app.get("/integrations", response_class=HTMLResponse)
async def integrations_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="integrations.html",
        context={"app_title": settings.app_title},
    )


@app.get("/usenet", response_class=HTMLResponse)
async def usenet_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="usenet.html",
        context={"app_title": settings.app_title},
    )


@app.get("/api/recommendations", response_model=RecommendationResponse)
async def get_recommendations(
    user_id: str = Query(default="default"),
    count: int = Query(default=12, ge=1, le=100),
    sources: str | None = Query(default=None),
    release_from: str | None = Query(default=None),
    release_to: str | None = Query(default=None),
    year_from: int | None = Query(default=None),
    year_to: int | None = Query(default=None),
) -> RecommendationResponse:
    required_sources = _parse_sources_query(sources)
    release_date_from = _parse_date_query(release_from)
    release_date_to = _parse_date_query(release_to)
    if release_date_from and release_date_to and release_date_from > release_date_to:
        release_date_from, release_date_to = release_date_to, release_date_from
    return await swarm.recommend_filtered(
        user_id=user_id,
        count=count,
        required_sources=required_sources,
        release_date_from=release_date_from,
        release_date_to=release_date_to,
        year_from=year_from,
        year_to=year_to,
    )


@app.get("/api/release-calendar")
async def get_release_calendar(
    user_id: str = Query(default="default"),
    sources: str | None = Query(default=None),
    release_from: str | None = Query(default=None),
    release_to: str | None = Query(default=None),
    limit: int = Query(default=1500, ge=1, le=5000),
) -> dict:
    required_sources = _parse_sources_query(sources)
    release_date_from = _parse_date_query(release_from)
    release_date_to = _parse_date_query(release_to)
    if release_date_from and release_date_to and release_date_from > release_date_to:
        release_date_from, release_date_to = release_date_to, release_date_from
    source_movies, _agent_statuses = await swarm.collect_sources(user_id=user_id, count=120)
    source_movies.pop("radarr", None)
    rows = _build_release_calendar(
        source_movies,
        required_sources=required_sources,
        release_date_from=release_date_from,
        release_date_to=release_date_to,
    )
    source_counts: dict[str, int] = {}
    for row in rows:
        for source in row["sources"]:
            source_counts[source] = source_counts.get(source, 0) + 1
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_items": len(rows),
        "source_counts": source_counts,
        "items": rows[:limit],
    }


@app.get("/api/usenet/releases")
async def get_usenet_releases(
    limit: int = Query(default=250, ge=1, le=2000),
    q: str | None = Query(default=None),
) -> dict:
    return await _crawl_usenet_releases(limit=limit, query=q)


@app.get("/api/trailer")
async def get_trailer(title: str = Query(...), year: int | None = Query(default=None)) -> dict:
    if not settings.tmdb_api_key:
        return {"ok": False, "video_key": None, "message": "TMDB not configured"}
    try:
        tmdb = TMDBClient(api_key=settings.tmdb_api_key, timeout_seconds=settings.source_timeout_seconds)
        results = await tmdb.search_movie(query=title.strip(), year=year)
        if not results:
            return {"ok": False, "video_key": None, "message": "Movie not found"}
        tmdb_id = results[0].get("id")
        if not tmdb_id:
            return {"ok": False, "video_key": None, "message": "No TMDB ID"}
        videos = await tmdb.movie_videos(tmdb_id)
        for v in videos:
            if v.get("site", "").lower() == "youtube" and v.get("type", "").lower() == "trailer":
                return {"ok": True, "video_key": v["key"]}
        for v in videos:
            if v.get("site", "").lower() == "youtube" and v.get("type", "").lower() == "teaser":
                return {"ok": True, "video_key": v["key"]}
        for v in videos:
            if v.get("site", "").lower() == "youtube":
                return {"ok": True, "video_key": v["key"]}
        return {"ok": False, "video_key": None, "message": "No YouTube trailer found"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "video_key": None, "message": str(exc)}


@app.get("/api/search")
async def search_movies(q: str = Query(..., min_length=1)) -> dict:
    if not settings.tmdb_api_key:
        return {"ok": False, "results": [], "message": "TMDB not configured"}

    try:
        tmdb = TMDBClient(api_key=settings.tmdb_api_key, timeout_seconds=settings.source_timeout_seconds)
        raw = await tmdb.search_movie(query=q.strip())
        results = []
        for m in raw[:20]:
            poster_path = m.get("poster_path")
            poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
            backdrop_path = m.get("backdrop_path")
            backdrop_url = f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else None
            release = m.get("release_date") or ""
            year = int(release[:4]) if len(release) >= 4 else None
            results.append({
                "tmdb_id": m.get("id"),
                "title": m.get("title"),
                "year": year,
                "overview": m.get("overview", ""),
                "poster_url": poster_url,
                "backdrop_url": backdrop_url,
                "vote_average": m.get("vote_average"),
                "release_date": release,
            })
        return {"ok": True, "results": results}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "results": [], "message": str(exc)}


@app.get("/api/radarr-monitored")
async def get_radarr_monitored() -> dict:
    if not settings.radarr_api_key:
        return {"configured": False, "ok": False, "movies": [], "message": "Radarr not configured"}

    try:
        movies = await RadarrClient(
            base_url=settings.radarr_base_url,
            api_key=settings.radarr_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        ).movies()

        items = []
        for m in movies:
            status = str(m.get("status") or "unknown").lower()
            monitored = bool(m.get("monitored"))
            has_file = bool(m.get("hasFile"))
            is_available = bool(m.get("isAvailable"))

            if has_file:
                state = "downloaded"
            elif status == "released" and is_available and monitored:
                state = "waiting"
            elif monitored:
                state = "monitored"
            else:
                state = "unmonitored"

            items.append({
                "movie_id": m.get("id"),
                "title": m.get("title"),
                "year": m.get("year"),
                "monitored": monitored,
                "has_file": has_file,
                "status": status,
                "is_available": is_available,
                "state": state,
                "digital_release": m.get("digitalRelease"),
                "physical_release": m.get("physicalRelease"),
                "in_cinemas": m.get("inCinemas"),
            })

        items.sort(key=lambda x: (
            {"downloaded": 2, "waiting": 0, "monitored": 1, "unmonitored": 3}.get(x["state"], 4),
            x.get("title") or "",
        ))

        return {"configured": True, "ok": True, "radarr_base_url": settings.radarr_base_url, "movies": items}
    except Exception as exc:  # noqa: BLE001
        return {"configured": True, "ok": False, "movies": [], "message": str(exc)}


@app.get("/api/download-health")
async def get_download_health() -> dict:
    if not settings.radarr_api_key:
        return {
            "configured": False,
            "ok": False,
            "message": "Radarr API key not configured",
            "queue_count": 0,
            "active_count": 0,
            "download_rate_human": None,
            "items": [],
        }

    try:
        queue_rows = await RadarrClient(
            base_url=settings.radarr_base_url,
            api_key=settings.radarr_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        ).queue_details()
        payload = _build_download_health_payload(queue_rows)
        return {"configured": True, "ok": True, "message": "ok", "radarr_base_url": settings.radarr_base_url, **payload}
    except Exception as exc:  # noqa: BLE001
        return {
            "configured": True,
            "ok": False,
            "message": str(exc),
            "queue_count": 0,
            "active_count": 0,
            "download_rate_human": None,
            "items": [],
        }


@app.get("/api/download-history")
async def get_download_history(limit: int = Query(default=40, ge=1, le=200)) -> dict:
    if not settings.radarr_api_key:
        return {
            "configured": False,
            "ok": False,
            "message": "Radarr API key not configured",
            "items": [],
        }

    try:
        rows = await RadarrClient(
            base_url=settings.radarr_base_url,
            api_key=settings.radarr_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        ).history(limit=limit)
        return {
            "configured": True,
            "ok": True,
            "message": "ok",
            "items": _build_download_history_payload(rows, limit=limit),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "configured": True,
            "ok": False,
            "message": str(exc),
            "items": [],
        }


@app.post("/api/download-history/clear")
async def clear_download_history(payload: DownloadHistoryClearRequest) -> dict:
    if not settings.radarr_api_key:
        return {
            "status": "error",
            "message": "Radarr API key not configured",
            "auto_download": payload.auto_download,
            "auto_delete": payload.auto_delete,
            "grabbed_count": 0,
            "deleted_count": 0,
            "queued_count": 0,
            "cleared_at": datetime.now(UTC).isoformat(),
            "errors": [],
        }

    client = RadarrClient(
        base_url=settings.radarr_base_url,
        api_key=settings.radarr_api_key,
        timeout_seconds=settings.source_timeout_seconds,
    )
    rows = await client.history(limit=payload.limit)

    grabbed_movie_ids: set[int] = set()
    history_ids: list[int] = []
    for row in rows:
        row_id = row.get("id")
        try:
            if row_id is not None:
                history_ids.append(int(row_id))
        except (TypeError, ValueError):
            pass

        event = str(row.get("eventType") or "").strip().lower()
        if event != "grabbed":
            continue
        movie = row.get("movie") if isinstance(row.get("movie"), dict) else {}
        movie_id = row.get("movieId") or movie.get("id")
        if movie_id is None:
            continue
        try:
            grabbed_movie_ids.add(int(movie_id))
        except (TypeError, ValueError):
            continue

    deleted_count = 0
    queued_count = 0
    errors: list[str] = []
    if payload.auto_delete:
        for history_id in history_ids:
            try:
                await client.delete_history_item(history_id)
                deleted_count += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"delete:{history_id}: {exc}")

    # auto_download disabled — never re-trigger downloads automatically

    return {
        "status": "ok",
        "message": "history clear completed",
        "auto_download": payload.auto_download,
        "auto_delete": payload.auto_delete,
        "grabbed_count": len(grabbed_movie_ids),
        "deleted_count": deleted_count,
        "queued_count": queued_count,
        "cleared_at": datetime.now(UTC).isoformat(),
        "errors": errors[:10],
    }


@app.post("/api/download-cancel")
async def cancel_download(payload: DownloadCancelRequest) -> dict:
    if not settings.radarr_api_key:
        return {"ok": False, "message": "Radarr API key not configured"}

    try:
        client = RadarrClient(
            base_url=settings.radarr_base_url,
            api_key=settings.radarr_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        )
        await client.remove_queue_item(
            queue_id=payload.queue_id,
            remove_from_client=payload.remove_from_client,
            blocklist=payload.blocklist,
        )
        return {"ok": True, "message": f"Cancelled queue item {payload.queue_id}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc)}


@app.post("/api/download-cancel-all")
async def cancel_all_downloads() -> dict:
    if not settings.radarr_api_key:
        return {"ok": False, "cancelled": 0, "errors": [], "message": "Radarr API key not configured"}

    try:
        client = RadarrClient(
            base_url=settings.radarr_base_url,
            api_key=settings.radarr_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        )
        queue_rows = await client.queue_details()
        cancelled = 0
        errors: list[str] = []
        for row in queue_rows:
            queue_id = row.get("id")
            if queue_id is None:
                continue
            try:
                await client.remove_queue_item(
                    queue_id=int(queue_id),
                    remove_from_client=True,
                    blocklist=False,
                )
                cancelled += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"queue:{queue_id}: {exc}")
        return {
            "ok": True,
            "cancelled": cancelled,
            "total": len(queue_rows),
            "errors": errors[:10],
            "message": f"Cancelled {cancelled}/{len(queue_rows)} queue items",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "cancelled": 0, "errors": [str(exc)], "message": str(exc)}


@app.post("/api/feedback")
async def post_feedback(payload: FeedbackInput) -> dict:
    await memory_store.add_feedback(payload)
    category = "watch" if payload.liked else "skipped"
    memory_store.upsert_seen(
        SeenMovieInput(
            user_id=payload.user_id,
            movie_id=payload.movie_id,
            title=payload.title,
            year=payload.year,
            source=category,
        )
    )

    return {"status": "ok", "seen_source": category}


class DownloadMovieRequest(BaseModel):
    title: str
    year: int | None = None


@app.post("/api/monitor")
async def monitor_movie(payload: DownloadMovieRequest) -> dict:
    if not settings.radarr_api_key:
        return {"ok": False, "status": "skipped", "message": "Radarr not configured"}
    try:
        result = await RadarrClient(
            base_url=settings.radarr_base_url,
            api_key=settings.radarr_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        ).ensure_movie_monitored(title=payload.title, year=payload.year)
        return {"ok": True, **result}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "error", "message": str(exc)}


@app.post("/api/download")
async def download_movie(payload: DownloadMovieRequest) -> dict:
    if not settings.radarr_api_key:
        return {"ok": False, "status": "skipped", "message": "Radarr not configured"}

    try:
        result = await RadarrClient(
            base_url=settings.radarr_base_url,
            api_key=settings.radarr_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        ).ensure_movie_wanted(title=payload.title, year=payload.year)
        return {"ok": True, **result}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "error", "message": str(exc)}


@app.get("/api/feedback/{user_id}", response_model=list[FeedbackRow])
async def get_feedback(user_id: str) -> list[FeedbackRow]:
    return memory_store.recent_feedback(user_id=user_id, limit=100)


@app.get("/api/seen/{user_id}", response_model=list[SeenMovieRow])
async def get_seen_movies(
    user_id: str,
    limit: int = Query(default=500, ge=1, le=2000),
    q: str | None = Query(default=None),
) -> list[SeenMovieRow]:
    return memory_store.list_seen(user_id=user_id, limit=limit, query=q)


@app.post("/api/seen")
async def add_seen_movie(payload: SeenMovieInput) -> dict:
    memory_store.upsert_seen(payload)
    return {"status": "ok"}


@app.delete("/api/seen")
async def remove_seen_movie(payload: SeenMovieDeleteInput) -> dict:
    removed = memory_store.remove_seen(user_id=payload.user_id, movie_id=payload.movie_id)
    return {"status": "ok", "removed": removed}


@app.post("/api/seen/import/plex")
async def import_seen_from_plex(
    user_id: str = Query(default="default"),
) -> dict:
    if not settings.plex_token:
        return {"ok": False, "imported": 0, "message": "PLEX_TOKEN missing"}

    rows = await PlexClient(
        base_url=settings.plex_base_url,
        token=settings.plex_token,
        timeout_seconds=settings.source_timeout_seconds,
    ).library_movies()

    imported = 0
    for row in rows:
        title = row.get("title")
        if not title:
            continue
        rating_key = row.get("ratingKey")
        year = row.get("year")
        movie_id = (
            f"plex:{rating_key}"
            if rating_key
            else f"plex:{title.strip().lower().replace(' ', '_')}::{year if year is not None else 'na'}"
        )
        memory_store.upsert_seen(
            SeenMovieInput(
                user_id=user_id,
                movie_id=movie_id,
                title=title,
                year=year,
                source="plex",
            )
        )
        imported += 1

    return {
        "ok": True,
        "imported": imported,
        "total": len(rows),
        "message": f"Imported {imported} movies from Plex library",
    }


@app.get("/api/plex/library")
async def plex_library(
    limit: int = Query(default=600, ge=1, le=2000),
    q: str | None = Query(default=None),
) -> dict:
    if not settings.plex_token:
        return {"ok": False, "movies": [], "message": "PLEX_TOKEN missing"}

    rows = await PlexClient(
        base_url=settings.plex_base_url,
        token=settings.plex_token,
        timeout_seconds=settings.source_timeout_seconds,
    ).library_movies()

    query = (q or "").strip().lower()
    movies: list[dict] = []
    for row in rows:
        title = row.get("title")
        if not title:
            continue
        if query and query not in title.lower():
            continue
        year = row.get("year")
        rating_key = row.get("ratingKey")
        movie_id = (
            f"plex:{rating_key}"
            if rating_key
            else f"plex:{title.strip().lower().replace(' ', '_')}::{year if year is not None else 'na'}"
        )
        movies.append(
            {
                "movie_id": movie_id,
                "title": title,
                "year": year,
            }
        )

    movies.sort(key=lambda row: (row["title"].lower(), row.get("year") or 0))
    return {"ok": True, "total": len(movies), "movies": movies[:limit]}


@app.get("/api/integrations")
async def integration_status() -> dict:
    return await _integration_status()


@app.get("/api/settings")
async def get_settings() -> dict:
    return {"values": _to_public_settings_values(), "defaults": DEFAULT_URLS}


@app.post("/api/settings")
async def save_settings(payload: IntegrationSettingsPayload) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    if updates:
        _save_settings(updates)
        await _reload_runtime()
    return {
        "status": "ok",
        "integrations": await _integration_status(),
        "values": _to_public_settings_values(),
    }


@app.post("/api/integrations/test")
async def test_integration(payload: IntegrationTestRequest) -> dict:
    integration = payload.integration
    values = _effective_settings_values(
        payload.values.model_dump(exclude_unset=True) if payload.values else None
    )

    try:
        if integration == "tmdb":
            if not values["tmdb_api_key"]:
                return {"ok": False, "integration": integration, "message": "TMDB_API_KEY missing"}
            rows = await TMDBClient(
                api_key=values["tmdb_api_key"],
                timeout_seconds=settings.source_timeout_seconds,
            ).upcoming_movies(page=1)
            return {
                "ok": True,
                "integration": integration,
                "message": f"TMDB reachable ({len(rows)} upcoming rows)",
            }

        if integration == "rottentomatoes":
            if not values["rottentomatoes_list_url"]:
                return {
                    "ok": False,
                    "integration": integration,
                    "message": "ROTTENTOMATOES_LIST_URL missing",
                }
            rows = await RottenTomatoesClient(settings.source_timeout_seconds).browse_movies(
                values["rottentomatoes_list_url"]
            )
            return {
                "ok": True,
                "integration": integration,
                "message": f"Rotten Tomatoes reachable ({len(rows)} parsed rows)",
            }

        if integration == "releases":
            if not values["releases_url"]:
                return {"ok": False, "integration": integration, "message": "RELEASES_URL missing"}
            rows = await ReleasesClient(settings.source_timeout_seconds).upcoming_movies(
                values["releases_url"]
            )
            return {
                "ok": True,
                "integration": integration,
                "message": f"Releases.com reachable ({len(rows)} parsed rows)",
            }

        if integration == "rogerebert":
            if not values["rogerebert_reviews_url"]:
                return {
                    "ok": False,
                    "integration": integration,
                    "message": "ROGEREBERT_REVIEWS_URL missing",
                }
            rows = await RogerEbertClient(settings.source_timeout_seconds).recent_reviews(
                values["rogerebert_reviews_url"],
                limit=20,
            )
            recent_rows = [row for row in rows if row.get("year") in {2025, 2026}]
            return {
                "ok": True,
                "integration": integration,
                "message": (
                    f"RogerEbert reachable ({len(recent_rows)} rows for years 2025/2026, "
                    f"{len(rows)} total parsed)"
                ),
            }

        if integration == "plex":
            if not values["plex_token"]:
                return {"ok": False, "integration": integration, "message": "PLEX_TOKEN missing"}
            rows = await PlexClient(
                base_url=values["plex_base_url"],
                token=values["plex_token"],
                timeout_seconds=settings.source_timeout_seconds,
            ).library_movies()
            return {
                "ok": True,
                "integration": integration,
                "message": f"Plex reachable ({len(rows)} movies)",
            }

        if integration == "radarr":
            if not values["radarr_api_key"]:
                return {"ok": False, "integration": integration, "message": "RADARR_API_KEY missing"}
            rows = await RadarrClient(
                base_url=values["radarr_base_url"],
                api_key=values["radarr_api_key"],
                timeout_seconds=settings.source_timeout_seconds,
            ).movies()
            return {
                "ok": True,
                "integration": integration,
                "message": f"Radarr reachable ({len(rows)} tracked movies)",
            }

        if integration == "nzbgeek":
            if not values["nzbgeek_rss_url"]:
                return {"ok": False, "integration": integration, "message": "NZBGEEK_RSS_URL missing"}
            if (
                ("{API_KEY}" in values["nzbgeek_rss_url"] or "${API_KEY}" in values["nzbgeek_rss_url"])
                and not values["nzbgeek_api_key"]
            ):
                return {"ok": False, "integration": integration, "message": "NZBGEEK_API_KEY missing"}
            rows = await UsenetClient(
                base_url="https://api.nzbgeek.info",
                api_key=values["nzbgeek_api_key"] or "",
                timeout_seconds=settings.source_timeout_seconds,
            ).movie_rss_feed(
                rss_url=values["nzbgeek_rss_url"],
                api_key=values["nzbgeek_api_key"],
            )
            return {
                "ok": True,
                "integration": integration,
                "message": f"NZBGeek RSS reachable ({len(rows)} items)",
            }

        if integration == "drunkenslug":
            if not values["drunkenslug_api_key"]:
                return {"ok": False, "integration": integration, "message": "DRUNKENSLUG_API_KEY missing"}
            rows = await UsenetClient(
                base_url=values["drunkenslug_base_url"],
                api_key=values["drunkenslug_api_key"],
                timeout_seconds=settings.source_timeout_seconds,
            ).movie_search(query="")
            return {
                "ok": True,
                "integration": integration,
                "message": f"DrunkenSlug reachable ({len(rows)} rows)",
            }

        if integration == "usenet":
            if not values["usenet_api_key"]:
                return {"ok": False, "integration": integration, "message": "USENET_API_KEY missing"}
            rows = await UsenetClient(
                base_url=values["usenet_base_url"],
                api_key=values["usenet_api_key"],
                timeout_seconds=settings.source_timeout_seconds,
            ).movie_search(query="")
            return {
                "ok": True,
                "integration": integration,
                "message": f"Usenet indexer reachable ({len(rows)} rows)",
            }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "integration": integration, "message": str(exc)}

    return {"ok": False, "integration": integration, "message": "Unsupported integration"}
