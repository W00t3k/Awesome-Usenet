from __future__ import annotations

from app.clients.http_client import HTTPClient


class RadarrClient:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: float):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http = HTTPClient(timeout_seconds)

    async def movies(self) -> list[dict]:
        return await self._http.get_json(
            f"{self._base_url}/api/v3/movie",
            headers={"X-Api-Key": self._api_key},
        )
