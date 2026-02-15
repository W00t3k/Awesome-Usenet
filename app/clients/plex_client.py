from __future__ import annotations

import httpx
from urllib.parse import urlparse

from app.clients.http_client import HTTPClient


class PlexClient:
    def __init__(self, base_url: str, token: str, timeout_seconds: float):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = httpx.Timeout(timeout_seconds)
        self._http = HTTPClient(timeout_seconds)

    def _headers(self) -> dict[str, str]:
        return {"X-Plex-Token": self._token, "Accept": "application/json"}

    def _server_connection(self) -> dict[str, int | str]:
        parsed = urlparse(self._base_url)
        protocol = (parsed.scheme or "http").strip() or "http"
        address = (parsed.hostname or "127.0.0.1").strip() or "127.0.0.1"
        if parsed.port is not None:
            port = int(parsed.port)
        else:
            port = 443 if protocol == "https" else 80
        return {
            "protocol": protocol,
            "address": address,
            "port": port,
        }

    async def library_movies(self) -> list[dict]:
        directories = await self.movie_sections()
        movies: list[dict] = []
        for section in directories:
            section_key = section.get("key")
            if not section_key:
                continue
            payload = await self._http.get_json(
                f"{self._base_url}/library/sections/{section_key}/all",
                headers=self._headers(),
            )
            movies.extend(payload.get("MediaContainer", {}).get("Metadata", []))
        return movies

    async def movie_sections(self) -> list[dict]:
        sections = await self._http.get_json(
            f"{self._base_url}/library/sections",
            headers=self._headers(),
        )
        directories = (
            sections.get("MediaContainer", {}).get("Directory", [])
            if isinstance(sections, dict)
            else []
        )
        return [section for section in directories if section.get("type") == "movie" and section.get("key")]

    async def server_machine_identifier(self) -> str:
        payload = await self._http.get_json(
            f"{self._base_url}/",
            headers=self._headers(),
        )
        container = payload.get("MediaContainer", {}) if isinstance(payload, dict) else {}
        machine_identifier = str(container.get("machineIdentifier") or "").strip()
        if not machine_identifier:
            raise ValueError("Could not resolve Plex machine identifier")
        return machine_identifier

    async def list_clients(self) -> list[dict]:
        payload = await self._http.get_json(
            f"{self._base_url}/clients",
            headers=self._headers(),
        )
        container = payload.get("MediaContainer", {}) if isinstance(payload, dict) else {}
        rows = container.get("Server", [])
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            return []

        clients: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            client_identifier = str(row.get("machineIdentifier") or row.get("clientIdentifier") or "").strip()
            if not client_identifier:
                continue
            try:
                last_seen_at = int(row.get("lastSeenAt") or 0)
            except (TypeError, ValueError):
                last_seen_at = 0
            clients.append(
                {
                    "client_identifier": client_identifier,
                    "name": str(row.get("name") or "").strip(),
                    "product": str(row.get("product") or "").strip(),
                    "platform": str(row.get("platform") or "").strip(),
                    "device": str(row.get("device") or "").strip(),
                    "host": str(row.get("host") or "").strip(),
                    "port": str(row.get("port") or "").strip(),
                    "last_seen_at": last_seen_at,
                }
            )
        clients.sort(key=lambda item: (int(item.get("last_seen_at") or 0), str(item.get("name") or "").casefold()), reverse=True)
        return clients

    async def resolve_playback_client(self, preferred: str | None = None) -> dict | None:
        clients = await self.list_clients()
        if not clients:
            return None

        token = str(preferred or "").strip()
        if token:
            needle = token.casefold()
            for row in clients:
                if str(row.get("client_identifier") or "").casefold() == needle:
                    return row
            for row in clients:
                if str(row.get("name") or "").casefold() == needle:
                    return row
            for row in clients:
                haystack = " ".join(
                    [
                        str(row.get("name") or ""),
                        str(row.get("product") or ""),
                        str(row.get("platform") or ""),
                        str(row.get("device") or ""),
                    ]
                ).casefold()
                if needle in haystack:
                    return row

        def _score(row: dict) -> tuple[int, int]:
            text = " ".join(
                [
                    str(row.get("name") or ""),
                    str(row.get("product") or ""),
                    str(row.get("platform") or ""),
                    str(row.get("device") or ""),
                ]
            ).casefold()
            score = 0
            if "sony" in text or "bravia" in text:
                score += 12
            if "tv" in text:
                score += 8
            if "android" in text:
                score += 4
            if "web" in text or "browser" in text:
                score -= 6
            return score, int(row.get("last_seen_at") or 0)

        clients.sort(key=_score, reverse=True)
        return clients[0]

    async def create_video_play_queue(self, rating_key: str) -> dict:
        key = str(rating_key or "").strip()
        if not key:
            raise ValueError("No rating key provided for play queue")

        machine_id = await self.server_machine_identifier()
        uri = f"server://{machine_id}/com.plexapp.plugins.library/library/metadata/{key}"

        payload: dict = {}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/playQueues",
                params={
                    "type": "video",
                    "continuous": 0,
                    "uri": uri,
                    "shuffle": 0,
                },
                headers=self._headers(),
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError:
                payload = {}

        container = payload.get("MediaContainer", {}) if isinstance(payload, dict) else {}
        play_queue_id = str(container.get("playQueueID") or container.get("playQueueId") or "").strip()
        if not play_queue_id:
            raise ValueError("Plex play queue creation returned no queue id")
        return {
            "play_queue_id": play_queue_id,
            "selected_item_id": str(container.get("playQueueSelectedItemID") or "").strip(),
        }

    async def start_playback(
        self,
        *,
        rating_key: str,
        client_identifier: str | None = None,
        offset_ms: int = 0,
    ) -> dict:
        key = str(rating_key or "").strip()
        if not key:
            raise ValueError("No rating key provided for playback")

        target = await self.resolve_playback_client(preferred=client_identifier)
        if not target:
            raise ValueError("No Plex playback client found. Open Plex on your TV/device first.")

        machine_id = await self.server_machine_identifier()
        play_queue = await self.create_video_play_queue(key)
        connection = self._server_connection()
        offset_value = max(0, int(offset_ms))
        params = {
            "key": f"/library/metadata/{key}",
            "type": "video",
            "offset": offset_value,
            "machineIdentifier": machine_id,
            "protocol": connection["protocol"],
            "address": connection["address"],
            "port": int(connection["port"]),
            "containerKey": f"/playQueues/{play_queue['play_queue_id']}?window=100&own=1",
            "commandID": 1,
        }
        headers = self._headers()
        headers["X-Plex-Target-Client-Identifier"] = str(target.get("client_identifier") or "")

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                f"{self._base_url}/player/playback/playMedia",
                params=params,
                headers=headers,
            )
            response.raise_for_status()

        return {
            "client": target,
            "play_queue_id": play_queue.get("play_queue_id"),
            "offset_ms": offset_value,
            "rating_key": key,
        }

    async def list_video_playlists(self) -> list[dict]:
        payload = await self._http.get_json(
            f"{self._base_url}/playlists",
            headers=self._headers(),
        )
        rows = payload.get("MediaContainer", {}).get("Metadata", []) if isinstance(payload, dict) else []
        return [row for row in rows if str(row.get("playlistType") or "") in ("", "video")]

    async def find_playlist_by_title(self, title: str) -> dict | None:
        target = (title or "").strip().casefold()
        if not target:
            return None
        for row in await self.list_video_playlists():
            current = str(row.get("title") or "").strip().casefold()
            if current == target:
                return row
        return None

    async def delete_playlist(self, rating_key: str) -> None:
        key = str(rating_key or "").strip()
        if not key:
            return
        await self._http.delete(
            f"{self._base_url}/playlists/{key}",
            headers=self._headers(),
        )

    async def create_video_playlist(self, title: str, rating_keys: list[str]) -> dict:
        cleaned_keys = [str(key).strip() for key in rating_keys if str(key).strip()]
        if not cleaned_keys:
            raise ValueError("No rating keys provided for playlist")

        machine_id = await self.server_machine_identifier()
        uri = f"server://{machine_id}/com.plexapp.plugins.library/library/metadata/{','.join(cleaned_keys)}"

        payload: dict = {}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/playlists",
                params={
                    "type": "video",
                    "title": title.strip() or "Majic TV Station",
                    "smart": 0,
                    "uri": uri,
                },
                headers=self._headers(),
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError:
                payload = {}

        metadata = payload.get("MediaContainer", {}).get("Metadata", []) if isinstance(payload, dict) else []
        if metadata:
            return metadata[0]

        row = await self.find_playlist_by_title(title)
        if row:
            return row
        raise ValueError("Plex playlist creation returned no metadata")

    async def upsert_video_playlist(self, title: str, rating_keys: list[str]) -> dict:
        existing = await self.find_playlist_by_title(title)
        if existing:
            key = str(existing.get("ratingKey") or "").strip()
            if key:
                await self.delete_playlist(key)
        return await self.create_video_playlist(title=title, rating_keys=rating_keys)

    async def list_collections(self, section_key: str) -> list[dict]:
        payload = await self._http.get_json(
            f"{self._base_url}/library/sections/{section_key}/collections",
            headers=self._headers(),
        )
        container = payload.get("MediaContainer", {}) if isinstance(payload, dict) else {}
        rows: list[dict] = []
        for field in ("Metadata", "Directory"):
            value = container.get(field, [])
            if isinstance(value, list):
                rows.extend(value)
            elif isinstance(value, dict):
                rows.append(value)

        collections: list[dict] = []
        for row in rows:
            row_type = str(row.get("type") or "").strip().lower()
            row_key = str(row.get("key") or "").strip().lower()
            if row_type == "collection" or "/library/collections/" in row_key:
                collections.append(row)
        return collections

    async def find_collections_by_title(self, section_key: str, title: str) -> list[dict]:
        target = (title or "").strip().casefold()
        if not target:
            return []
        matches = []
        for row in await self.list_collections(section_key):
            current = str(row.get("title") or "").strip().casefold()
            if current == target:
                matches.append(row)
        return matches

    async def find_collection_by_title(self, section_key: str, title: str) -> dict | None:
        matches = await self.find_collections_by_title(section_key=section_key, title=title)
        if not matches:
            return None

        def to_int(value: object) -> int:
            try:
                return int(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return 0

        matches.sort(
            key=lambda row: (
                to_int(row.get("childCount")),
                to_int(row.get("updatedAt")),
                to_int(row.get("ratingKey")),
            ),
            reverse=True,
        )
        return matches[0]

    async def delete_collection(self, rating_key: str) -> None:
        key = str(rating_key or "").strip()
        if not key:
            return
        await self._http.delete(
            f"{self._base_url}/library/collections/{key}",
            headers=self._headers(),
        )

    async def create_collection(self, section_key: str, title: str, rating_keys: list[str]) -> dict:
        cleaned_keys = [str(key).strip() for key in rating_keys if str(key).strip()]
        if not cleaned_keys:
            raise ValueError("No rating keys provided for collection")

        machine_id = await self.server_machine_identifier()
        uri = f"server://{machine_id}/com.plexapp.plugins.library/library/metadata/{','.join(cleaned_keys)}"

        payload: dict = {}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/library/collections",
                params={
                    "type": 1,
                    "title": title.strip() or "Majic TV Station",
                    "smart": 0,
                    "sectionId": section_key,
                    "uri": uri,
                },
                headers=self._headers(),
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError:
                payload = {}

        metadata = payload.get("MediaContainer", {}).get("Metadata", []) if isinstance(payload, dict) else []
        if metadata:
            return metadata[0]

        row = await self.find_collection_by_title(section_key=section_key, title=title)
        if row:
            return row
        raise ValueError("Plex collection creation returned no metadata")

    async def upsert_collection(self, section_key: str, title: str, rating_keys: list[str]) -> dict:
        existing_rows = await self.find_collections_by_title(section_key=section_key, title=title)
        for existing in existing_rows:
            key = str(existing.get("ratingKey") or "").strip()
            if key:
                await self.delete_collection(key)
        return await self.create_collection(section_key=section_key, title=title, rating_keys=rating_keys)
