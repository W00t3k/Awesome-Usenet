from __future__ import annotations

import json
import re
from typing import Any

from app.clients.http_client import HTTPClient


class RottenTomatoesClient:
    def __init__(self, timeout_seconds: float):
        self._http = HTTPClient(timeout_seconds)

    async def browse_movies(self, list_url: str) -> list[dict[str, Any]]:
        html = await self._http.get_text(
            list_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                )
            },
        )
        payload = self._extract_jsonld_payload(html)
        return self._extract_movies(payload)

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

            if RottenTomatoesClient._extract_movies(payload):
                return payload

        raise ValueError("No movie JSON-LD payload found on Rotten Tomatoes page")

    @staticmethod
    def _extract_movies(payload: Any) -> list[dict[str, Any]]:
        movies: list[dict[str, Any]] = []
        for idx, movie in enumerate(RottenTomatoesClient._iter_movie_nodes(payload), start=1):
            title = movie.get("name")
            if not title:
                continue
            rating = RottenTomatoesClient._as_int(
                movie.get("aggregateRating", {}).get("ratingValue")
            )
            reviews = RottenTomatoesClient._as_int(
                movie.get("aggregateRating", {}).get("reviewCount")
            )
            year = RottenTomatoesClient._as_int(movie.get("dateCreated"))
            raw_genre = movie.get("genre")
            if isinstance(raw_genre, list):
                genres = [str(g).strip() for g in raw_genre if isinstance(g, str) and g.strip()]
            elif isinstance(raw_genre, str) and raw_genre.strip():
                genres = [g.strip() for g in raw_genre.split(",") if g.strip()]
            else:
                genres = []

            movies.append(
                {
                    "position": RottenTomatoesClient._as_int(movie.get("position")) or idx,
                    "title": title,
                    "year": year,
                    "tomatometer": rating,
                    "review_count": reviews,
                    "url": movie.get("url"),
                    "image": RottenTomatoesClient._as_url(movie.get("image")),
                    "genres": genres,
                }
            )

        movies.sort(key=lambda row: row.get("position") or 9999)
        return movies

    @staticmethod
    def _iter_movie_nodes(node: Any):
        if isinstance(node, list):
            for item in node:
                yield from RottenTomatoesClient._iter_movie_nodes(item)
            return

        if not isinstance(node, dict):
            return

        if str(node.get("@type", "")).lower() == "movie":
            yield node
            return

        for key in ("itemListElement", "item"):
            if key in node:
                yield from RottenTomatoesClient._iter_movie_nodes(node[key])

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
                parsed = RottenTomatoesClient._as_url(item)
                if parsed:
                    return parsed
        return None
