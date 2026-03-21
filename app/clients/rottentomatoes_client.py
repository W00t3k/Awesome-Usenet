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
        rows = self._extract_movies(payload)
        if rows:
            return rows

        # Fallback: parse any JSON script payload and extract movie-like rows
        generic_rows = self._extract_movies_from_json_scripts(html)
        if generic_rows:
            return generic_rows

        raise ValueError("No movie payload found on Rotten Tomatoes page")

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
    def _extract_json_payloads(html: str) -> list[Any]:
        payloads: list[Any] = []
        script_blocks = re.findall(
            r'<script[^>]*type=["\']application/(?:ld\+)?json["\'][^>]*>(.*?)</script>',
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
            payloads.append(payload)
        return payloads

    @staticmethod
    def _extract_movies_from_json_scripts(html: str) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for payload in RottenTomatoesClient._extract_json_payloads(html):
            rows = RottenTomatoesClient._extract_movies(payload)
            if not rows:
                rows = RottenTomatoesClient._extract_movies_from_generic_payload(payload)
            for row in rows:
                title = str(row.get("title") or "").strip()
                year = row.get("year")
                if not title:
                    continue
                key = f"{title.lower()}::{year if isinstance(year, int) else 'na'}"
                if key not in merged:
                    merged[key] = row
                    continue
                existing = merged[key]
                if existing.get("tomatometer") is None and row.get("tomatometer") is not None:
                    existing["tomatometer"] = row.get("tomatometer")
                if not existing.get("url") and row.get("url"):
                    existing["url"] = row.get("url")
                if not existing.get("image") and row.get("image"):
                    existing["image"] = row.get("image")
                if not existing.get("genres") and row.get("genres"):
                    existing["genres"] = row.get("genres")

        rows = list(merged.values())
        rows.sort(key=lambda row: (row.get("position") or 9999, str(row.get("title") or "").lower()))
        return rows

    @staticmethod
    def _extract_movies_from_generic_payload(payload: Any) -> list[dict[str, Any]]:
        movies: list[dict[str, Any]] = []
        for idx, node in enumerate(RottenTomatoesClient._iter_dict_nodes(payload), start=1):
            title = RottenTomatoesClient._as_str(
                node.get("title"),
                node.get("name"),
                node.get("movieTitle"),
            )
            if not title:
                continue

            rating = RottenTomatoesClient._extract_tomatometer(node)
            if rating is None:
                continue

            year = RottenTomatoesClient._as_int(
                node.get("year"),
                node.get("releaseYear"),
                node.get("dateCreated"),
                node.get("releaseDate"),
            )
            reviews = RottenTomatoesClient._as_int(
                node.get("review_count"),
                node.get("reviewCount"),
                node.get("totalReviews"),
                node.get("reviewsCount"),
                node.get("criticReviewsCount"),
            )
            url = RottenTomatoesClient._as_url(
                node.get("url"),
                node.get("movieUrl"),
                node.get("canonicalUrl"),
                node.get("href"),
            )
            if isinstance(url, str) and url.startswith("/"):
                url = f"https://www.rottentomatoes.com{url}"
            image = RottenTomatoesClient._as_url(
                node.get("image"),
                node.get("poster_url"),
                node.get("posterUrl"),
                node.get("poster"),
            )
            raw_genres = node.get("genres", node.get("genre"))
            if isinstance(raw_genres, list):
                genres = [str(g).strip() for g in raw_genres if str(g).strip()]
            elif isinstance(raw_genres, str):
                genres = [g.strip() for g in raw_genres.split(",") if g.strip()]
            else:
                genres = []

            movies.append(
                {
                    "position": RottenTomatoesClient._as_int(node.get("position")) or idx,
                    "title": title,
                    "year": year,
                    "tomatometer": rating,
                    "review_count": reviews,
                    "url": url,
                    "image": image,
                    "genres": genres,
                }
            )
        return movies

    @staticmethod
    def _iter_dict_nodes(node: Any):
        if isinstance(node, dict):
            yield node
            for value in node.values():
                yield from RottenTomatoesClient._iter_dict_nodes(value)
        elif isinstance(node, list):
            for item in node:
                yield from RottenTomatoesClient._iter_dict_nodes(item)

    @staticmethod
    def _extract_tomatometer(node: dict[str, Any]) -> int | None:
        direct = RottenTomatoesClient._as_int(
            node.get("tomatometer"),
            node.get("tomatometerScore"),
            node.get("meterScore"),
            node.get("tomatoScore"),
            node.get("criticsScore"),
            node.get("criticScore"),
        )
        if direct is not None:
            return max(0, min(100, direct))

        score_blocks = [
            node.get("scores"),
            node.get("aggregateRating"),
            node.get("tomatometer"),
            node.get("tomatometerScore"),
            node.get("meter"),
            node.get("criticScore"),
        ]
        for block in score_blocks:
            if isinstance(block, dict):
                nested = RottenTomatoesClient._as_int(
                    block.get("score"),
                    block.get("value"),
                    block.get("tomatometer"),
                    block.get("ratingValue"),
                    block.get("criticsScore"),
                )
                if nested is not None:
                    return max(0, min(100, nested))
        return None

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
    def _as_int(*values: Any) -> int | None:
        for value in values:
            if value is None:
                continue
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(value)
            text = str(value).strip()
            if not text:
                continue
            year_match = re.search(r"(19|20)\d{2}", text)
            if year_match:
                return int(year_match.group(0))
            int_match = re.search(r"\d+", text)
            if int_match:
                return int(int_match.group(0))
        return None

    @staticmethod
    def _as_str(*values: Any) -> str | None:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    @staticmethod
    def _as_url(*values: Any) -> str | None:
        for value in values:
            if isinstance(value, str):
                if value:
                    return value
                continue
            if isinstance(value, dict):
                for key in ("url", "contentUrl", "thumbnailUrl", "src"):
                    url = value.get(key)
                    if isinstance(url, str) and url:
                        return url
            if isinstance(value, list):
                for item in value:
                    parsed = RottenTomatoesClient._as_url(item)
                    if parsed:
                        return parsed
        return None
