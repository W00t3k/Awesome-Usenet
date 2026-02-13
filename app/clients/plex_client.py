from __future__ import annotations

from app.clients.http_client import HTTPClient


class PlexClient:
    def __init__(self, base_url: str, token: str, timeout_seconds: float):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._http = HTTPClient(timeout_seconds)

    async def library_movies(self) -> list[dict]:
        sections = await self._http.get_json(
            f"{self._base_url}/library/sections",
            headers={"X-Plex-Token": self._token, "Accept": "application/json"},
        )
        directories = (
            sections.get("MediaContainer", {}).get("Directory", [])
            if isinstance(sections, dict)
            else []
        )

        movies: list[dict] = []
        for section in directories:
            if section.get("type") != "movie":
                continue
            section_key = section.get("key")
            if not section_key:
                continue
            payload = await self._http.get_json(
                f"{self._base_url}/library/sections/{section_key}/all",
                headers={"X-Plex-Token": self._token, "Accept": "application/json"},
            )
            movies.extend(payload.get("MediaContainer", {}).get("Metadata", []))
        return movies
