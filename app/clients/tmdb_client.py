from __future__ import annotations

from typing import Any

from app.clients.http_client import HTTPClient


class TMDBClient:
    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self, api_key: str, timeout_seconds: float):
        self._api_key = api_key
        self._is_bearer = api_key.startswith("eyJ")
        self._http = HTTPClient(timeout_seconds)

    def _request_kwargs(self, extra_params: dict[str, Any] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"language": "en-US"}
        if extra_params:
            params.update(extra_params)
        headers: dict[str, str] | None = None
        if self._is_bearer:
            headers = {"Authorization": f"Bearer {self._api_key}"}
        else:
            params["api_key"] = self._api_key
        return {"params": params, "headers": headers}

    async def upcoming_movies(self, page: int = 1) -> list[dict]:
        kwargs = self._request_kwargs({"page": page})
        payload = await self._http.get_json(
            f"{self.BASE_URL}/movie/upcoming", **kwargs,
        )
        return payload.get("results", [])

    async def upcoming_movies_all(self, max_pages: int = 10) -> list[dict]:
        """Fetch ALL upcoming movies across multiple pages."""
        all_movies: list[dict] = []
        page = 1
        while page <= max_pages:
            kwargs = self._request_kwargs({"page": page})
            payload = await self._http.get_json(
                f"{self.BASE_URL}/movie/upcoming", **kwargs,
            )
            results = payload.get("results", [])
            if not results:
                break
            all_movies.extend(results)
            total_pages = payload.get("total_pages", 1)
            if page >= total_pages:
                break
            page += 1
        return all_movies

    async def now_playing_all(self, max_pages: int = 5) -> list[dict]:
        """Fetch ALL now playing movies across multiple pages."""
        all_movies: list[dict] = []
        page = 1
        while page <= max_pages:
            kwargs = self._request_kwargs({"page": page})
            payload = await self._http.get_json(
                f"{self.BASE_URL}/movie/now_playing", **kwargs,
            )
            results = payload.get("results", [])
            if not results:
                break
            all_movies.extend(results)
            total_pages = payload.get("total_pages", 1)
            if page >= total_pages:
                break
            page += 1
        return all_movies

    async def discover_movies_for_year(
        self, year: int, max_pages: int = 10, sort_by: str = "popularity.desc"
    ) -> list[dict]:
        """Fetch ALL movies from TMDB for a specific year."""
        all_movies: list[dict] = []
        page = 1
        while page <= max_pages:
            extra: dict[str, Any] = {
                "primary_release_year": year,
                "sort_by": sort_by,
                "page": page,
            }
            kwargs = self._request_kwargs(extra)
            payload = await self._http.get_json(
                f"{self.BASE_URL}/discover/movie", **kwargs,
            )
            results = payload.get("results", [])
            if not results:
                break
            all_movies.extend(results)
            total_pages = payload.get("total_pages", 1)
            if page >= total_pages:
                break
            page += 1
        return all_movies

    async def discover_movies(
        self,
        year_from: int | None = None,
        year_to: int | None = None,
        page: int = 1,
        sort_by: str = "vote_count.desc",
    ) -> list[dict]:
        extra: dict[str, Any] = {
            "sort_by": sort_by,
            "page": page,
            "vote_count.gte": 50,
        }
        if year_from:
            extra["primary_release_date.gte"] = f"{year_from}-01-01"
        if year_to:
            extra["primary_release_date.lte"] = f"{year_to}-12-31"
        kwargs = self._request_kwargs(extra)
        payload = await self._http.get_json(
            f"{self.BASE_URL}/discover/movie", **kwargs,
        )
        return payload.get("results", [])

    async def movie_videos(self, tmdb_id: int) -> list[dict]:
        kwargs = self._request_kwargs()
        payload = await self._http.get_json(
            f"{self.BASE_URL}/movie/{tmdb_id}/videos", **kwargs,
        )
        return payload.get("results", [])

    async def search_movie(self, query: str, year: int | None = None) -> list[dict]:
        extra: dict[str, Any] = {"query": query}
        if year:
            extra["year"] = year
        kwargs = self._request_kwargs(extra)
        payload = await self._http.get_json(
            f"{self.BASE_URL}/search/movie", **kwargs,
        )
        return payload.get("results", [])
