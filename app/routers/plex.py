from __future__ import annotations

import logging
import random
from urllib.parse import quote

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app import state
from app.config import limits, settings
from app.clients.plex_client import PlexClient

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Pydantic models ────────────────────────────────────────────────────────────

class PlexWatchlistRequest(BaseModel):
    title: str
    year: int | None = None
    tmdb_id: int | None = None
    imdb_id: str | None = None
    server_id: int | None = None


class PlexStationStartRequest(BaseModel):
    name: str = "Random Plex TV"
    count: int = Field(default=30, ge=1, le=250)
    seed: int | None = None
    min_year: int | None = None
    max_year: int | None = None


class PlexChannelRefreshRequest(BaseModel):
    playlist_name: str | None = None
    count: int | None = Field(default=None, ge=1, le=250)
    seed: int | None = None
    min_year: int | None = None
    max_year: int | None = None


class PlexChannelScheduleRequest(BaseModel):
    enabled: bool = True
    playlist_name: str = "Majic TV Station"
    count: int = Field(default=25, ge=1, le=250)
    min_year: int | None = None
    max_year: int | None = None
    schedule_times: list[str] = Field(default_factory=lambda: ["20:00"])
    interval_minutes: int = Field(default=0, ge=0, le=1440)
    autoplay_enabled: bool = True
    autoplay_client: str | None = None
    autoplay_random_offset: bool = True
    run_now: bool = False


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_plex_config(server_id: int | None = None) -> tuple[str, str] | None:
    if server_id:
        server = state.memory_store.get_server(server_id)
        if server and server["service_type"] == "plex":
            return server["base_url"], server.get("api_key")
        return None
    default = state.memory_store.get_default_server("plex")
    if default:
        return default["base_url"], default.get("api_key")
    if settings.plex_token:
        return settings.plex_base_url, settings.plex_token
    return None


def get_radarr_config(server_id: int | None = None) -> tuple[str, str] | None:
    from app.clients.radarr_client import RadarrClient  # noqa: F401
    if server_id:
        server = state.memory_store.get_server(server_id)
        if server and server["service_type"] == "radarr":
            return server["base_url"], server.get("api_key")
        return None
    default = state.memory_store.get_default_server("radarr")
    if default:
        return default["base_url"], default.get("api_key")
    if settings.radarr_api_key:
        return settings.radarr_base_url, settings.radarr_api_key
    return None


def _plex_web_url_for_rating_key(rating_key: str | None) -> str | None:
    if not rating_key:
        return None
    key = quote(f"/library/metadata/{rating_key}", safe="")
    return f"{settings.plex_base_url.rstrip('/')}/web/index.html#!/details?key={key}"


def _plex_thumb_url(path: str | None) -> str | None:
    thumb = str(path or "").strip()
    if not thumb:
        return None
    token = (settings.plex_token or "").strip()
    if not token:
        return None
    return f"{settings.plex_base_url.rstrip('/')}{thumb}?X-Plex-Token={token}"


def _plex_playlist_web_url(rating_key: str | None) -> str | None:
    key = str(rating_key or "").strip()
    if not key:
        return None
    encoded = quote(f"/playlists/{key}", safe="")
    return f"{settings.plex_base_url.rstrip('/')}/web/index.html#!/details?key={encoded}"


def _plex_collection_web_url(rating_key: str | None) -> str | None:
    key = str(rating_key or "").strip()
    if not key:
        return None
    encoded = quote(f"/library/collections/{key}", safe="")
    return f"{settings.plex_base_url.rstrip('/')}/web/index.html#!/details?key={encoded}"


def _enrich_station_payload(station: dict | None) -> dict | None:
    if not station:
        return station

    def enrich_item(item: dict | None) -> dict | None:
        if not isinstance(item, dict):
            return item
        enriched = dict(item)
        enriched["web_url"] = _plex_web_url_for_rating_key(enriched.get("rating_key"))
        enriched["poster_url"] = _plex_thumb_url(enriched.get("thumb"))
        return enriched

    enriched_station = dict(station)
    enriched_station["now_playing"] = enrich_item(enriched_station.get("now_playing"))
    enriched_station["up_next"] = [enrich_item(i) for i in (enriched_station.get("up_next") or [])]
    enriched_station["queue"] = [enrich_item(i) for i in (enriched_station.get("queue") or [])]
    return enriched_station


async def _refresh_plex_tv_channel(
    *,
    reason: str,
    scheduled_slot: str | None = None,
    override_playlist_name: str | None = None,
    override_count: int | None = None,
    override_seed: int | None = None,
    override_min_year: int | None = None,
    override_max_year: int | None = None,
) -> dict:
    if not settings.plex_token:
        raise ValueError("PLEX_TOKEN missing")

    schedule_snap = state.plex_channel_schedule.snapshot()
    playlist_name = (override_playlist_name or schedule_snap.get("playlist_name") or "Majic TV Station").strip() or "Majic TV Station"
    count = max(1, min(int(override_count if override_count is not None else int(schedule_snap.get("count") or 25)), 250))
    min_year = int(override_min_year) if override_min_year is not None else schedule_snap.get("min_year")
    max_year = int(override_max_year) if override_max_year is not None else schedule_snap.get("max_year")
    if min_year is not None and max_year is not None and min_year > max_year:
        min_year, max_year = max_year, min_year

    client = PlexClient(base_url=settings.plex_base_url, token=settings.plex_token, timeout_seconds=settings.source_timeout_seconds)

    try:
        rows = await client.library_movies()
        queue = state.plex_station_service.build_queue(rows, count=count, seed=override_seed, min_year=min_year, max_year=max_year)
        rating_keys = [k for k in (str(item.get("rating_key") or "").strip() for item in queue) if k]
        if not rating_keys:
            raise ValueError("No eligible Plex rating keys found for channel queue")

        playlist = await client.upsert_video_playlist(title=playlist_name, rating_keys=rating_keys)
        playlist_key = str(playlist.get("ratingKey") or "").strip()
        playlist_url = _plex_playlist_web_url(playlist_key)

        collection_payload: dict | None = None
        movie_sections = await client.movie_sections()
        if movie_sections:
            section_key = str(movie_sections[0].get("key") or "").strip()
            if section_key:
                collection = await client.upsert_collection(section_key=section_key, title=playlist_name, rating_keys=rating_keys)
                collection_key = str(collection.get("ratingKey") or "").strip()
                collection_payload = {
                    "title": collection.get("title"), "rating_key": collection_key,
                    "item_count": collection.get("childCount"), "web_url": _plex_collection_web_url(collection_key),
                }

        queue_preview = [
            {"title": item.get("title"), "year": item.get("year"), "rating_key": item.get("rating_key"),
             "poster_url": _plex_thumb_url(item.get("thumb")), "web_url": _plex_web_url_for_rating_key(item.get("rating_key"))}
            for item in queue[:12]
        ]

        autoplay_enabled = bool(schedule_snap.get("autoplay_enabled", True))
        autoplay_client = str(schedule_snap.get("autoplay_client") or "").strip() or None
        autoplay_random_offset = bool(schedule_snap.get("autoplay_random_offset", True))
        autoplay_result: dict | None = None
        run_message = f"Updated '{playlist_name}' with {len(rating_keys)} movies."

        if autoplay_enabled and queue:
            movie = random.choice(queue)
            movie_title = str(movie.get("title") or "").strip() or "Unknown title"
            movie_rating_key = str(movie.get("rating_key") or "").strip()
            try:
                duration_ms = int(movie.get("duration_ms") or 0)
            except (TypeError, ValueError):
                duration_ms = 0
            offset_ms = 0
            if autoplay_random_offset and duration_ms > (45 * 60 * 1000):
                max_offset_ms = max(0, duration_ms - (20 * 60 * 1000))
                if max_offset_ms > 0:
                    offset_ms = random.randint(0, max_offset_ms)

            if movie_rating_key:
                try:
                    playback = await client.start_playback(rating_key=movie_rating_key, client_identifier=autoplay_client, offset_ms=offset_ms)
                    target = playback.get("client") or {}
                    target_name = str(target.get("name") or target.get("client_identifier") or "").strip() or None
                    state.plex_channel_schedule.mark_playback(success=True, message=f"Started '{movie_title}' on '{target_name or 'unknown client'}'.", movie_title=movie_title, client_name=target_name, offset_ms=int(playback.get("offset_ms") or 0))
                    autoplay_result = {"ok": True, "movie_title": movie_title, "offset_ms": int(playback.get("offset_ms") or 0), "client": target}
                    run_message = f"{run_message} Started '{movie_title}' on {target_name or 'client'}."
                except Exception as exc:
                    error_message = str(exc)
                    state.plex_channel_schedule.mark_playback(success=False, message=error_message, movie_title=movie_title, client_name=autoplay_client, offset_ms=offset_ms)
                    autoplay_result = {"ok": False, "movie_title": movie_title, "offset_ms": offset_ms, "message": error_message}
                    run_message = f"{run_message} Playback not started: {error_message}"

        schedule_state = state.plex_channel_schedule.mark_run(success=True, message=run_message, queue_size=len(rating_keys), source=reason, slot=scheduled_slot)
        return {
            "ok": True,
            "playlist": {"title": playlist_name, "rating_key": playlist_key, "item_count": len(rating_keys), "web_url": playlist_url},
            "collection": collection_payload,
            "queue_preview": queue_preview,
            "autoplay": autoplay_result,
            "schedule": schedule_state,
        }
    except Exception as exc:
        state.plex_channel_schedule.mark_run(success=False, message=str(exc), queue_size=0, source=reason, slot=scheduled_slot)
        raise


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/api/plex/library")
async def plex_library(
    limit: int = Query(default=600, ge=1, le=limits.browse_max),
    q: str | None = Query(default=None),
    server_id: int | None = Query(default=None),
) -> dict:
    plex_config = get_plex_config(server_id)
    if not plex_config:
        return {"ok": False, "movies": [], "message": "No Plex server configured"}
    base_url, token = plex_config
    if not token:
        return {"ok": False, "movies": [], "message": "Plex token missing"}

    rows = await PlexClient(base_url=base_url, token=token, timeout_seconds=settings.source_timeout_seconds).library_movies()
    query = (q or "").strip().lower()
    movies: list[dict] = []
    for row in rows:
        title = row.get("title")
        if not title or (query and query not in title.lower()):
            continue
        year = row.get("year")
        rating_key = row.get("ratingKey")
        movie_id = (f"plex:{rating_key}" if rating_key else f"plex:{title.strip().lower().replace(' ', '_')}::{year if year is not None else 'na'}")
        movies.append({"movie_id": movie_id, "title": title, "year": year})
    movies.sort(key=lambda r: (r["title"].lower(), r.get("year") or 0))
    return {"ok": True, "total": len(movies), "movies": movies[:limit]}


@router.post("/api/plex/watchlist")
async def add_to_plex_watchlist(req: PlexWatchlistRequest) -> dict:
    plex_config = get_plex_config(req.server_id)
    if not plex_config:
        return {"ok": False, "message": "No Plex server configured"}
    base_url, token = plex_config
    if not token:
        return {"ok": False, "message": "Plex token missing"}

    import httpx
    headers = {"X-Plex-Token": token, "X-Plex-Client-Identifier": "majic-movie-selector", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            rating_key = None
            if req.tmdb_id:
                resp = await client.get(f"https://discover.provider.plex.tv/library/search?query=tmdb://{req.tmdb_id}&searchTypes=movie&limit=1", headers=headers)
                if resp.status_code == 200:
                    results = resp.json().get("MediaContainer", {}).get("Metadata", [])
                    if results:
                        rating_key = results[0].get("ratingKey")

            if not rating_key:
                query = f"{req.title} {req.year}" if req.year else req.title
                resp = await client.get(f"https://discover.provider.plex.tv/library/search?query={quote(query)}&searchTypes=movie&limit=5", headers=headers)
                if resp.status_code == 200:
                    results = resp.json().get("MediaContainer", {}).get("Metadata", [])
                    for result in results:
                        if result.get("title", "").lower() == req.title.lower():
                            if not req.year or result.get("year") == req.year:
                                rating_key = result.get("ratingKey")
                                break
                    if not rating_key and results:
                        rating_key = results[0].get("ratingKey")

            if not rating_key:
                return {"ok": False, "message": f"Could not find '{req.title}' on Plex"}

            resp = await client.put(f"https://discover.provider.plex.tv/actions/addToWatchlist?ratingKey={rating_key}", headers=headers)
            if resp.status_code in (200, 201, 204):
                return {"ok": True, "message": f"Added '{req.title}' to Plex Watchlist"}
            return {"ok": False, "message": f"Failed to add to watchlist: {resp.status_code}"}
    except Exception as exc:
        logger.error(f"Error adding to Plex Watchlist: {exc}")
        return {"ok": False, "message": str(exc)}


@router.post("/api/plex/station/start")
async def start_plex_station(payload: PlexStationStartRequest) -> dict:
    if not settings.plex_token:
        return {"ok": False, "message": "PLEX_TOKEN missing"}
    min_year = payload.min_year
    max_year = payload.max_year
    if min_year is not None and max_year is not None and min_year > max_year:
        min_year, max_year = max_year, min_year
    rows = await PlexClient(base_url=settings.plex_base_url, token=settings.plex_token, timeout_seconds=settings.source_timeout_seconds).library_movies()
    try:
        station = state.plex_station_service.create_station(rows, name=payload.name, count=payload.count, seed=payload.seed, min_year=min_year, max_year=max_year)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "station": _enrich_station_payload(station)}


@router.get("/api/plex/station")
async def list_plex_stations() -> dict:
    stations = [_enrich_station_payload(s) for s in state.plex_station_service.list_stations()]
    return {"ok": True, "stations": stations}


@router.get("/api/plex/station/{station_id}")
async def get_plex_station(station_id: str) -> dict:
    station = state.plex_station_service.get_station(station_id)
    if not station:
        return {"ok": False, "message": "Station not found"}
    return {"ok": True, "station": _enrich_station_payload(station)}


@router.post("/api/plex/station/{station_id}/next")
async def next_plex_station_movie(station_id: str) -> dict:
    try:
        station = state.plex_station_service.next_movie(station_id)
    except KeyError:
        return {"ok": False, "message": "Station not found"}
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "station": _enrich_station_payload(station)}


@router.delete("/api/plex/station/{station_id}")
async def delete_plex_station(station_id: str) -> dict:
    removed = state.plex_station_service.delete_station(station_id)
    return {"ok": True, "removed": removed}


@router.get("/api/plex/channel/status")
async def plex_channel_status() -> dict:
    schedule_state = state.plex_channel_schedule.snapshot()
    configured = bool(settings.plex_token)
    channel = {"configured": configured, "mode": "plex_playlist", "plays_in": "Plex clients (TV, mobile, web) via Playlists and Movies Collections", "schedule": schedule_state, "playlist": None, "collection": None}
    if not configured:
        return {"ok": True, "channel": channel, "message": "PLEX_TOKEN missing"}
    try:
        client = PlexClient(base_url=settings.plex_base_url, token=settings.plex_token, timeout_seconds=settings.source_timeout_seconds)
        title = str(schedule_state.get("playlist_name") or "Majic TV Station")
        playlist = await client.find_playlist_by_title(title)
        if playlist:
            key = str(playlist.get("ratingKey") or "").strip()
            channel["playlist"] = {"title": playlist.get("title"), "rating_key": key, "item_count": playlist.get("leafCount"), "duration_ms": playlist.get("duration"), "web_url": _plex_playlist_web_url(key)}
        movie_sections = await client.movie_sections()
        if movie_sections:
            section_key = str(movie_sections[0].get("key") or "").strip()
            if section_key:
                collection = await client.find_collection_by_title(section_key=section_key, title=title)
                if collection:
                    collection_key = str(collection.get("ratingKey") or "").strip()
                    channel["collection"] = {"title": collection.get("title"), "rating_key": collection_key, "item_count": collection.get("childCount"), "web_url": _plex_collection_web_url(collection_key)}
    except Exception as exc:
        channel["playlist_error"] = str(exc)
    return {"ok": True, "channel": channel}


@router.get("/api/plex/clients")
async def plex_clients() -> dict:
    if not settings.plex_token:
        return {"ok": False, "clients": [], "message": "PLEX_TOKEN missing"}
    try:
        client = PlexClient(base_url=settings.plex_base_url, token=settings.plex_token, timeout_seconds=settings.source_timeout_seconds)
        rows = await client.list_clients()
        selected = await client.resolve_playback_client()
        return {"ok": True, "clients": rows, "selected": selected}
    except Exception as exc:
        return {"ok": False, "clients": [], "message": str(exc)}


@router.post("/api/plex/channel/refresh")
async def refresh_plex_channel(payload: PlexChannelRefreshRequest | None = None) -> dict:
    req = payload or PlexChannelRefreshRequest()
    try:
        return await _refresh_plex_tv_channel(reason="manual", override_playlist_name=req.playlist_name, override_count=req.count, override_seed=req.seed, override_min_year=req.min_year, override_max_year=req.max_year)
    except Exception as exc:
        return {"ok": False, "message": str(exc), "schedule": state.plex_channel_schedule.snapshot()}


@router.post("/api/plex/channel/run")
async def run_plex_channel(payload: PlexChannelRefreshRequest | None = None) -> dict:
    req = payload or PlexChannelRefreshRequest()
    try:
        return await _refresh_plex_tv_channel(reason="manual-run", override_playlist_name=req.playlist_name, override_count=req.count, override_seed=req.seed, override_min_year=req.min_year, override_max_year=req.max_year)
    except Exception as exc:
        return {"ok": False, "message": str(exc), "schedule": state.plex_channel_schedule.snapshot()}


@router.post("/api/plex/channel/schedule")
async def update_plex_channel_schedule(payload: PlexChannelScheduleRequest) -> dict:
    try:
        schedule_state = state.plex_channel_schedule.update_config(
            enabled=payload.enabled, playlist_name=payload.playlist_name, count=payload.count,
            min_year=payload.min_year, max_year=payload.max_year, schedule_times=payload.schedule_times,
            interval_minutes=payload.interval_minutes, autoplay_enabled=payload.autoplay_enabled,
            autoplay_client=payload.autoplay_client, autoplay_random_offset=payload.autoplay_random_offset,
        )
    except ValueError as exc:
        return {"ok": False, "message": str(exc), "schedule": state.plex_channel_schedule.snapshot()}

    refresh_payload = None
    if payload.run_now:
        try:
            refresh_payload = await _refresh_plex_tv_channel(reason="schedule-run-now", override_playlist_name=payload.playlist_name, override_count=payload.count, override_min_year=payload.min_year, override_max_year=payload.max_year)
        except Exception as exc:
            return {"ok": False, "message": str(exc), "schedule": state.plex_channel_schedule.snapshot()}

    return {"ok": True, "schedule": schedule_state, "refresh": refresh_payload}


@router.post("/api/plex/channel/schedule/disable")
async def disable_plex_channel_schedule() -> dict:
    current = state.plex_channel_schedule.snapshot()
    schedule_state = state.plex_channel_schedule.update_config(
        enabled=False,
        playlist_name=str(current.get("playlist_name") or "Majic TV Station"),
        count=int(current.get("count") or 25),
        min_year=current.get("min_year"), max_year=current.get("max_year"),
        schedule_times=list(current.get("schedule_times") or ["20:00"]),
        interval_minutes=int(current.get("interval_minutes") or 0),
        autoplay_enabled=bool(current.get("autoplay_enabled", True)),
        autoplay_client=(str(current.get("autoplay_client") or "").strip() or None),
        autoplay_random_offset=bool(current.get("autoplay_random_offset", True)),
    )
    return {"ok": True, "schedule": schedule_state}
