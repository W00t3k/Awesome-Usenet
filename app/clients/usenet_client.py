from __future__ import annotations

from app.clients.http_client import HTTPClient


class UsenetClient:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: float):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http = HTTPClient(timeout_seconds)

    async def movie_search(self, query: str = "") -> list[dict]:
        payload = await self._http.get_json(
            f"{self._base_url}/api",
            params={
                "apikey": self._api_key,
                "t": "search",
                "cat": "2000",  # Movies category (Newznab)
                "q": query,
                "o": "json",
                "limit": 100,
            },
        )
        return payload.get("channel", {}).get("item", [])
