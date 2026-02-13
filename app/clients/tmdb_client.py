from __future__ import annotations

from app.clients.http_client import HTTPClient


class TMDBClient:
    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self, api_key: str, timeout_seconds: float):
        self._api_key = api_key
        self._http = HTTPClient(timeout_seconds)

    async def upcoming_movies(self, page: int = 1) -> list[dict]:
        payload = await self._http.get_json(
            f"{self.BASE_URL}/movie/upcoming",
            params={"api_key": self._api_key, "page": page, "language": "en-US"},
        )
        return payload.get("results", [])
