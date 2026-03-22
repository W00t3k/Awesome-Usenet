from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app import state
from app.config import settings

router = APIRouter()


class ServerConfigPayload(BaseModel):
    service_type: Literal["plex", "radarr"]
    name: str
    base_url: str
    api_key: str | None = None
    is_default: bool = False


class ServerConfigUpdatePayload(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None


def _mask_key(server: dict) -> dict:
    if server.get("api_key"):
        key = server["api_key"]
        server["api_key_masked"] = f"{key[:4]}...{key[-4:]}" if len(key) > 8 else "****"
        del server["api_key"]
    else:
        server["api_key_masked"] = None
        server.pop("api_key", None)
    return server


@router.get("/api/servers")
async def list_servers(service_type: str | None = Query(default=None)) -> dict:
    servers = state.memory_store.list_servers(service_type=service_type)
    return {"ok": True, "servers": [_mask_key(s) for s in servers]}


@router.post("/api/servers")
async def create_server(payload: ServerConfigPayload) -> dict:
    server_id = state.memory_store.create_server(
        service_type=payload.service_type,
        name=payload.name,
        base_url=payload.base_url,
        api_key=payload.api_key,
        is_default=payload.is_default,
    )
    if server_id is None:
        return {"ok": False, "message": "Failed to create server (name may already exist)"}
    return {"ok": True, "server_id": server_id, "message": f"Created {payload.service_type} server '{payload.name}'"}


@router.get("/api/servers/{server_id}")
async def get_server(server_id: int) -> dict:
    server = state.memory_store.get_server(server_id)
    if not server:
        return {"ok": False, "message": "Server not found"}
    if server.get("api_key"):
        key = server["api_key"]
        server["api_key_masked"] = f"{key[:4]}...{key[-4:]}" if len(key) > 8 else "****"
    return {"ok": True, "server": server}


@router.put("/api/servers/{server_id}")
async def update_server(server_id: int, payload: ServerConfigUpdatePayload) -> dict:
    if not state.memory_store.get_server(server_id):
        return {"ok": False, "message": "Server not found"}
    success = state.memory_store.update_server(
        server_id=server_id,
        name=payload.name,
        base_url=payload.base_url,
        api_key=payload.api_key,
    )
    return {"ok": success, "message": "Server updated" if success else "Failed to update server"}


@router.delete("/api/servers/{server_id}")
async def delete_server(server_id: int) -> dict:
    success = state.memory_store.delete_server(server_id)
    return {"ok": success, "message": "Server deleted" if success else "Server not found"}


@router.post("/api/servers/{server_id}/default")
async def set_default_server(server_id: int) -> dict:
    success = state.memory_store.set_default_server(server_id)
    return {"ok": success, "message": "Server set as default" if success else "Server not found"}


@router.post("/api/servers/{server_id}/test")
async def test_server(server_id: int) -> dict:
    from app.clients.plex_client import PlexClient
    from app.clients.radarr_client import RadarrClient

    server = state.memory_store.get_server(server_id)
    if not server:
        return {"ok": False, "message": "Server not found"}

    service_type = server["service_type"]
    base_url = server["base_url"]
    api_key = server.get("api_key")

    try:
        if service_type == "plex":
            if not api_key:
                return {"ok": False, "message": "Plex token required"}
            movies = await PlexClient(base_url=base_url, token=api_key, timeout_seconds=settings.source_timeout_seconds).library_movies()
            return {"ok": True, "message": f"Plex connected ({len(movies)} movies in library)"}
        if service_type == "radarr":
            if not api_key:
                return {"ok": False, "message": "Radarr API key required"}
            movies = await RadarrClient(base_url=base_url, api_key=api_key, timeout_seconds=settings.source_timeout_seconds).movies()
            return {"ok": True, "message": f"Radarr connected ({len(movies)} movies)"}
        return {"ok": False, "message": f"Unknown service type: {service_type}"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
