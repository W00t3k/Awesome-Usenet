from __future__ import annotations

import re
from typing import Any

from app.clients.http_client import HTTPClient
from app.clients.tmdb_client import TMDBClient


class PosterLookupClient:
    ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
    TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

    # TMDB genre ID to name mapping
    TMDB_GENRES = {
        28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime",
        99: "Documentary", 18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History",
        27: "Horror", 10402: "Music", 9648: "Mystery", 10749: "Romance",
        878: "Sci-Fi", 10770: "TV Movie", 53: "Thriller", 10752: "War", 37: "Western",
    }

    def __init__(self, timeout_seconds: float, tmdb_api_key: str | None = None):
        self._http = HTTPClient(timeout_seconds)
        self._cache: dict[str, Any] = {}
        self._tmdb_client = (
            TMDBClient(api_key=tmdb_api_key, timeout_seconds=timeout_seconds)
            if tmdb_api_key
            else None
        )

    async def poster_for(self, title: str, year: int | None = None) -> str | None:
        info = await self.lookup(title, year)
        return info.get("poster_url") if info else None

    async def lookup(self, title: str, year: int | None = None) -> dict[str, Any] | None:
        query = " ".join(part for part in [title.strip(), str(year) if year else ""] if part)
        cache_key = query.lower()
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if isinstance(cached, dict):
                return cached
            return {"poster_url": cached}

        result = await self._lookup_itunes(title, year)
        if not result or not result.get("poster_url"):
            tmdb_result = await self._lookup_tmdb(title, year)
            if tmdb_result:
                if result:
                    for k, v in tmdb_result.items():
                        if k not in result:
                            result[k] = v
                else:
                    result = tmdb_result

        # Only cache successful lookups — failed ones should be retried
        if result:
            self._cache[cache_key] = result
        return result or None

    async def _lookup_itunes(self, title: str, year: int | None = None) -> dict[str, Any] | None:
        query = " ".join(part for part in [title.strip(), str(year) if year else ""] if part)
        try:
            payload = await self._http.get_json(
                self.ITUNES_SEARCH_URL,
                params={"term": query, "entity": "movie", "media": "movie", "limit": 10},
            )
        except Exception:  # noqa: BLE001
            return None

        results = payload.get("results", []) if isinstance(payload, dict) else []
        for item in results:
            if not isinstance(item, dict):
                continue
            track_name = str(item.get("trackName") or "").strip()
            release_date = str(item.get("releaseDate") or "")
            item_year = self._extract_year(release_date)
            if not track_name:
                continue
            if not self._title_like_match(title, track_name):
                continue
            if year is not None and item_year is not None and abs(year - item_year) > 1:
                continue
            artwork = item.get("artworkUrl100") or item.get("artworkUrl60")
            poster_url = self._upgrade_artwork_url(artwork) if isinstance(artwork, str) and artwork else None
            overview = str(item.get("longDescription") or "").strip() or None
            genre = str(item.get("primaryGenreName") or "").strip() or None
            result: dict[str, Any] = {}
            if poster_url:
                result["poster_url"] = poster_url
            if overview:
                result["overview"] = overview
            if genre:
                result["genre"] = genre
            return result or None
        return None

    async def _lookup_tmdb(self, title: str, year: int | None = None) -> dict[str, Any] | None:
        if not self._tmdb_client:
            return None

        result = await self._tmdb_search_best(title, year)
        if result:
            return result

        # Retry without year for unreleased / upcoming movies
        if year is not None:
            result = await self._tmdb_search_best(title, None)
            if result:
                return result

        # Try with simplified title (remove common suffixes like Pilot, Part X, etc.)
        simplified = self._simplify_title(title)
        if simplified and simplified.lower() != title.lower():
            result = await self._tmdb_search_best(simplified, year)
            if result:
                return result
            if year is not None:
                result = await self._tmdb_search_best(simplified, None)
                if result:
                    return result

        return None

    @staticmethod
    def _simplify_title(title: str) -> str:
        """Remove common suffixes that might prevent TMDB matching."""
        import re
        # Remove common suffixes
        patterns = [
            r'\s+Pilot$',
            r'\s+Part\s*\d+$',
            r'\s+Episode\s*\d+$',
            r'\s+Chapter\s*\d+$',
            r'\s+Vol\.?\s*\d+$',
            r'\s+Volume\s*\d+$',
            r'\s+Season\s*\d+$',
            r'\s+S\d+E\d+$',
            r'\s+\d{4}$',  # Year at end
        ]
        result = title.strip()
        for pattern in patterns:
            result = re.sub(pattern, '', result, flags=re.IGNORECASE)
        return result.strip()

    async def _tmdb_search_best(self, title: str, year: int | None) -> dict[str, Any] | None:
        try:
            results = await self._tmdb_client.search_movie(query=title.strip(), year=year)
        except Exception:  # noqa: BLE001
            return None

        first_with_poster: dict[str, Any] | None = None

        for item in results:
            if not isinstance(item, dict):
                continue
            item_title = str(item.get("title") or "").strip()
            if not item_title:
                continue
            poster_path = item.get("poster_path")
            poster_url = f"{self.TMDB_IMAGE_BASE}{poster_path}" if poster_path else None
            overview = str(item.get("overview") or "").strip() or None

            # Extract genres from TMDB genre_ids
            genre_ids = item.get("genre_ids", [])
            genres = [self.TMDB_GENRES[gid] for gid in genre_ids if gid in self.TMDB_GENRES]

            # Strict title match — return immediately
            if self._title_like_match(title, item_title):
                result: dict[str, Any] = {}
                if poster_url:
                    result["poster_url"] = poster_url
                if overview:
                    result["overview"] = overview
                if genres:
                    result["genres"] = genres
                    result["genre"] = genres[0] if genres else None
                return result or None

            # Track first result that has a poster as fallback
            if poster_url and first_with_poster is None:
                first_with_poster = {"poster_url": poster_url}
                if overview:
                    first_with_poster["overview"] = overview
                if genres:
                    first_with_poster["genres"] = genres
                    first_with_poster["genre"] = genres[0] if genres else None

        # No strict match — accept the top TMDB result (search is relevance-ranked)
        return first_with_poster

    @staticmethod
    def _extract_year(text: str) -> int | None:
        match = re.search(r"(19|20)\d{2}", text)
        return int(match.group(0)) if match else None

    @staticmethod
    def _title_like_match(a: str, b: str) -> bool:
        normalize = lambda value: re.sub(r"[^a-z0-9]+", "", value.lower())
        strip_articles = lambda value: re.sub(r"\b(the|a|an)\b", "", value.lower())
        left = normalize(a)
        right = normalize(b)
        if not left or not right:
            return False
        if left == right:
            return True
        if left in right or right in left:
            return True
        left2 = normalize(strip_articles(a))
        right2 = normalize(strip_articles(b))
        if left2 and right2 and (left2 in right2 or right2 in left2):
            return True
        # Fuzzy: if the shorter string is at least 6 chars and matches 85%+ of the longer
        shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
        if len(shorter) >= 6:
            matches = sum(1 for i, c in enumerate(shorter) if i < len(longer) and c == longer[i])
            if matches / len(shorter) >= 0.85:
                return True
        return False

    @staticmethod
    def _upgrade_artwork_url(url: str) -> str:
        return url.replace("100x100bb", "600x600bb").replace("60x60bb", "600x600bb")
