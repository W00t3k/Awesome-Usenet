from __future__ import annotations

from typing import Any

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

    async def queue_details(self) -> list[dict]:
        payload = await self._http.get_json(
            f"{self._base_url}/api/v3/queue/details",
            params={"includeUnknownMovieItems": "true"},
            headers={"X-Api-Key": self._api_key},
        )
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            rows = payload.get("records")
            if isinstance(rows, list):
                return rows
        return []

    async def history(self, limit: int = 50) -> list[dict]:
        payload = await self._http.get_json(
            f"{self._base_url}/api/v3/history",
            params={
                "page": 1,
                "pageSize": max(1, min(limit, 200)),
                "sortDirection": "descending",
                "includeMovie": "true",
            },
            headers={"X-Api-Key": self._api_key},
        )
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            rows = payload.get("records")
            if isinstance(rows, list):
                return rows
        return []

    async def delete_history_item(self, history_id: int) -> None:
        await self._http.delete(
            f"{self._base_url}/api/v3/history/{history_id}",
            headers={"X-Api-Key": self._api_key},
        )

    async def lookup(self, term: str) -> list[dict]:
        return await self._http.get_json(
            f"{self._base_url}/api/v3/movie/lookup",
            params={"term": term},
            headers={"X-Api-Key": self._api_key},
        )

    async def quality_profiles(self) -> list[dict]:
        return await self._http.get_json(
            f"{self._base_url}/api/v3/qualityprofile",
            headers={"X-Api-Key": self._api_key},
        )

    async def root_folders(self) -> list[dict]:
        return await self._http.get_json(
            f"{self._base_url}/api/v3/rootfolder",
            headers={"X-Api-Key": self._api_key},
        )

    async def add_movie(
        self,
        lookup_result: dict[str, Any],
        quality_profile_id: int,
        root_folder_path: str,
        search_for_movie: bool = True,
    ) -> dict:
        payload = {
            "title": lookup_result.get("title"),
            "qualityProfileId": quality_profile_id,
            "titleSlug": lookup_result.get("titleSlug"),
            "images": lookup_result.get("images", []),
            "tmdbId": lookup_result.get("tmdbId"),
            "year": lookup_result.get("year"),
            "rootFolderPath": root_folder_path,
            "monitored": True,
            "minimumAvailability": "released",
            "addOptions": {"searchForMovie": search_for_movie},
        }
        return await self._http.post_json(
            f"{self._base_url}/api/v3/movie",
            payload=payload,
            headers={"X-Api-Key": self._api_key},
        )

    async def search_movie(self, movie_id: int) -> dict:
        return await self._http.post_json(
            f"{self._base_url}/api/v3/command",
            payload={"name": "MoviesSearch", "movieIds": [movie_id]},
            headers={"X-Api-Key": self._api_key},
        )

    async def remove_queue_item(
        self,
        queue_id: int,
        remove_from_client: bool = True,
        blocklist: bool = False,
    ) -> None:
        await self._http.delete(
            f"{self._base_url}/api/v3/queue/{queue_id}",
            params={
                "removeFromClient": "true" if remove_from_client else "false",
                "blocklist": "true" if blocklist else "false",
            },
            headers={"X-Api-Key": self._api_key},
        )

    async def ensure_movie_monitored(
        self,
        title: str,
        year: int | None = None,
    ) -> dict[str, str]:
        existing = await self.movies()
        normalized_title = title.strip().lower()
        for row in existing:
            row_title = str(row.get("title") or "").strip().lower()
            row_year = row.get("year")
            if row_title != normalized_title:
                continue
            if year is not None and row_year is not None and int(row_year) != int(year):
                continue
            return {"status": "exists", "message": "Already tracked in Radarr"}

        term = f"{title} {year}" if year else title
        lookup_rows = await self.lookup(term=term)
        candidate = None
        for row in lookup_rows:
            if str(row.get("title") or "").strip().lower() != normalized_title:
                continue
            row_year = row.get("year")
            if year is not None and row_year is not None and int(row_year) != int(year):
                continue
            candidate = row
            break
        if candidate is None and lookup_rows:
            candidate = lookup_rows[0]
        if not candidate:
            return {"status": "missing", "message": "No Radarr lookup match found"}

        profiles = await self.quality_profiles()
        roots = await self.root_folders()
        if not profiles:
            return {"status": "error", "message": "No quality profiles configured in Radarr"}
        if not roots:
            return {"status": "error", "message": "No root folders configured in Radarr"}

        quality_profile_id = int(profiles[0]["id"])
        root_folder_path = str(roots[0]["path"])
        await self.add_movie(
            lookup_result=candidate,
            quality_profile_id=quality_profile_id,
            root_folder_path=root_folder_path,
            search_for_movie=False,
        )
        return {"status": "monitored", "message": "Added to Radarr (monitoring only)"}

    async def ensure_movie_wanted(
        self,
        title: str,
        year: int | None = None,
    ) -> dict[str, str]:
        existing = await self.movies()
        normalized_title = title.strip().lower()
        for row in existing:
            row_title = str(row.get("title") or "").strip().lower()
            row_year = row.get("year")
            if row_title != normalized_title:
                continue
            if year is not None and row_year is not None and int(row_year) != int(year):
                continue
            movie_id = row.get("id")
            has_file = bool(row.get("hasFile") or row.get("movieFile"))
            if movie_id is not None and not has_file:
                await self.search_movie(int(movie_id))
                return {
                    "status": "queued",
                    "message": "Already tracked in Radarr; search requested",
                }
            if has_file:
                return {"status": "exists", "message": "Already downloaded in Radarr"}
            return {"status": "exists", "message": "Already tracked in Radarr"}

        term = f"{title} {year}" if year else title
        lookup_rows = await self.lookup(term=term)
        candidate = None
        for row in lookup_rows:
            if str(row.get("title") or "").strip().lower() != normalized_title:
                continue
            row_year = row.get("year")
            if year is not None and row_year is not None and int(row_year) != int(year):
                continue
            candidate = row
            break
        if candidate is None and lookup_rows:
            candidate = lookup_rows[0]
        if not candidate:
            return {"status": "missing", "message": "No Radarr lookup match found"}

        profiles = await self.quality_profiles()
        roots = await self.root_folders()
        if not profiles:
            return {"status": "error", "message": "No quality profiles configured in Radarr"}
        if not roots:
            return {"status": "error", "message": "No root folders configured in Radarr"}

        quality_profile_id = int(profiles[0]["id"])
        root_folder_path = str(roots[0]["path"])
        await self.add_movie(
            lookup_result=candidate,
            quality_profile_id=quality_profile_id,
            root_folder_path=root_folder_path,
            search_for_movie=True,
        )
        return {"status": "queued", "message": "Added to Radarr and search requested"}
