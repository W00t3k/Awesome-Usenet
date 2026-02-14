from __future__ import annotations

import json
import re
from typing import Any

from app.clients.http_client import HTTPClient


class ReleasesClient:
    def __init__(self, timeout_seconds: float):
        self._http = HTTPClient(timeout_seconds)

    async def upcoming_movies(self, url: str) -> list[dict[str, Any]]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        }
        errors: list[str] = []
        for candidate in self._candidate_urls(url):
            try:
                html = await self._http.get_text(candidate, headers=headers)
                if self._looks_like_cloudflare_challenge(html):
                    errors.append(f"{candidate}: blocked by Cloudflare challenge")
                    continue

                payload = self._extract_jsonld_payload(html)
                movies = self._extract_movies(payload)
                if movies:
                    return movies
                errors.append(f"{candidate}: no movie rows found")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{candidate}: {exc}")

        detail = "; ".join(errors[:3]) if errors else "no candidates were attempted"
        raise RuntimeError(f"Unable to parse Releases.com movie listings: {detail}")

    @staticmethod
    def _candidate_urls(url: str) -> list[str]:
        normalized = str(url or "").strip().rstrip("/")
        if not normalized:
            return []

        candidates: list[str] = [normalized]
        if normalized.endswith("/calendar/movie"):
            candidates.extend(
                [
                    normalized.replace("/calendar/movie", "/calendar/movies/upcoming"),
                    normalized.replace("/calendar/movie", "/calendar/movies/new"),
                ]
            )
        elif normalized.endswith("/calendar/movies"):
            candidates.extend(
                [
                    f"{normalized}/upcoming",
                    f"{normalized}/new",
                ]
            )

        deduped: list[str] = []
        for candidate in candidates:
            if candidate not in deduped:
                deduped.append(candidate)
        return deduped

    @staticmethod
    def _looks_like_cloudflare_challenge(html: str) -> bool:
        lowered = html.lower()
        return (
            "just a moment" in lowered
            and ("cf_chl_opt" in lowered or "_cf_chl_opt" in lowered)
            and ("challenge-platform" in lowered or "cdn-cgi/challenge-platform" in lowered)
        )

    @staticmethod
    def _extract_jsonld_payload(html: str) -> Any:
        script_blocks = re.findall(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for block in script_blocks:
            text = block.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue

            if ReleasesClient._extract_movies(payload):
                return payload

        raise ValueError("No releasable movie JSON-LD payload found on Releases page")

    @staticmethod
    def _extract_movies(payload: Any) -> list[dict[str, Any]]:
        movies: list[dict[str, Any]] = []
        for idx, movie in enumerate(ReleasesClient._iter_movie_nodes(payload), start=1):
            title = movie.get("name")
            if not title:
                continue

            release_date = (
                movie.get("datePublished")
                or movie.get("releaseDate")
                or movie.get("startDate")
                or movie.get("dateCreated")
            )
            year = ReleasesClient._as_int(release_date)
            movies.append(
                {
                    "position": ReleasesClient._as_int(movie.get("position")) or idx,
                    "title": title,
                    "release_date": release_date,
                    "year": year,
                    "url": movie.get("url"),
                    "image": ReleasesClient._as_url(movie.get("image")),
                    "overview": movie.get("description"),
                }
            )
        movies.sort(key=lambda row: row.get("position") or 9999)
        return movies

    @staticmethod
    def _iter_movie_nodes(node: Any):
        if isinstance(node, list):
            for item in node:
                yield from ReleasesClient._iter_movie_nodes(item)
            return

        if not isinstance(node, dict):
            return

        node_type = str(node.get("@type", "")).lower()
        if node_type in {"movie", "screeningevent"}:
            yield node
            return

        for key in ("itemListElement", "item", "subjectOf", "about"):
            if key in node:
                yield from ReleasesClient._iter_movie_nodes(node[key])

    @staticmethod
    def _as_int(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        text = str(value).strip()
        if not text:
            return None
        year_match = re.search(r"(19|20)\d{2}", text)
        if year_match:
            return int(year_match.group(0))
        int_match = re.search(r"\d+", text)
        if int_match:
            return int(int_match.group(0))
        return None

    @staticmethod
    def _as_url(value: Any) -> str | None:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("url", "contentUrl", "thumbnailUrl"):
                url = value.get(key)
                if isinstance(url, str) and url:
                    return url
        if isinstance(value, list):
            for item in value:
                parsed = ReleasesClient._as_url(item)
                if parsed:
                    return parsed
        return None
