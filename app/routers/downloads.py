from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app import state
from app.config import limits, settings
from app.clients.radarr_client import RadarrClient

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Pydantic models ────────────────────────────────────────────────────────────

class DownloadMovieRequest(BaseModel):
    title: str
    year: int | None = None


class DownloadHistoryClearRequest(BaseModel):
    auto_download: bool = True
    auto_delete: bool = True
    limit: int = 80


class DownloadCancelRequest(BaseModel):
    queue_id: int
    remove_from_client: bool = True
    blocklist: bool = False


class DownloadReleaseRequest(BaseModel):
    title: str
    year: int | None = None
    release_link: str
    indexer: str | None = None
    raw_title: str | None = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_radarr_config(server_id: int | None = None) -> tuple[str, str] | None:
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


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time_left_seconds(value: str | None) -> int | None:
    if not value:
        return None
    parts = [p for p in value.strip().split(":") if p != ""]
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = [int(p) for p in parts]
    except ValueError:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _human_bytes(value: float | None) -> str | None:
    if value is None:
        return None
    size = float(max(value, 0))
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    return f"{size:.1f} {units[idx]}"


def _human_size(bytes_val: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(bytes_val) < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} PB"


def _build_download_health_payload(queue_rows: list[dict]) -> dict:
    items: list[dict] = []
    total_rate = 0.0

    for row in queue_rows:
        movie = row.get("movie") if isinstance(row.get("movie"), dict) else {}
        title = str(movie.get("title") or row.get("title") or "Unknown title")
        year = movie.get("year")
        status = str(row.get("status") or row.get("trackedDownloadStatus") or row.get("trackedDownloadState") or "unknown")
        time_left = str(row.get("timeleft") or row.get("timeLeft") or "").strip() or None

        size_left = _as_float(row.get("sizeleft") or row.get("sizeLeft"))
        total_size = _as_float(row.get("size") or row.get("sizeBytes"))
        rate = _as_float(row.get("downloadClientRate") or row.get("downloadRate") or row.get("rate"))
        if rate is None and size_left is not None and time_left:
            secs = _parse_time_left_seconds(time_left)
            if secs and secs > 0:
                rate = size_left / secs

        if rate is not None and rate > 0:
            total_rate += rate

        progress = None
        if total_size and size_left is not None and total_size > 0:
            progress = max(0.0, min(100.0, ((total_size - size_left) / total_size) * 100.0))

        queue_id = row.get("id")
        try:
            queue_id = int(queue_id) if queue_id is not None else None
        except (TypeError, ValueError):
            queue_id = None

        movie_id = movie.get("id") or row.get("movieId")
        try:
            movie_id = int(movie_id) if movie_id is not None else None
        except (TypeError, ValueError):
            movie_id = None

        tmdb_id = movie.get("tmdbId")
        try:
            tmdb_id = int(tmdb_id) if tmdb_id is not None else None
        except (TypeError, ValueError):
            tmdb_id = None

        items.append({
            "queue_id": queue_id, "movie_id": movie_id, "tmdb_id": tmdb_id,
            "title": title, "year": year if isinstance(year, int) else None,
            "status": status, "time_left": time_left,
            "progress": round(progress, 1) if progress is not None else None,
            "size_left_human": _human_bytes(size_left), "total_size_human": _human_bytes(total_size),
            "rate_human": f"{_human_bytes(rate)}/s" if rate is not None else None,
        })

    active = [
        item for item in items
        if any(token in item["status"].lower() for token in ("downloading", "queued", "delay", "pending", "paused"))
    ] or items

    return {
        "queue_count": len(items), "active_count": len(active),
        "download_rate_human": f"{_human_bytes(total_rate)}/s" if total_rate > 0 else None,
        "items": active[:25],
    }


def _build_download_history_payload(rows: list[dict], limit: int) -> list[dict]:
    history: list[dict] = []
    for row in rows[:limit]:
        movie = row.get("movie") if isinstance(row.get("movie"), dict) else {}
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        history.append({
            "title": str(movie.get("title") or row.get("sourceTitle") or "Unknown title"),
            "year": movie.get("year") if isinstance(movie.get("year"), int) else None,
            "event": str(row.get("eventType") or "unknown"),
            "timestamp": row.get("date"),
            "download_client": data.get("downloadClient") or data.get("downloadClientName"),
            "source_title": row.get("sourceTitle"),
            "quality": (
                ((row.get("quality") or {}).get("quality") or {}).get("name")
                if isinstance(row.get("quality"), dict) else None
            ),
        })
    return history


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.delete("/api/radarr/movie/{movie_id}")
async def delete_radarr_movie(
    movie_id: int,
    delete_files: bool = Query(default=True),
    server_id: int | None = Query(default=None),
) -> dict:
    radarr_config = _get_radarr_config(server_id)
    if not radarr_config:
        return {"ok": False, "message": "No Radarr server configured"}
    base_url, api_key = radarr_config
    if not api_key:
        return {"ok": False, "message": "Radarr API key missing"}
    try:
        import httpx
        url = f"{base_url.rstrip('/')}/api/v3/movie/{movie_id}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(url, params={"deleteFiles": str(delete_files).lower(), "addImportExclusion": "false"}, headers={"X-Api-Key": api_key})
        if resp.status_code in (200, 204):
            return {"ok": True, "message": f"Movie {movie_id} deleted from Radarr"}
        return {"ok": False, "message": f"Radarr returned {resp.status_code}"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


@router.get("/api/radarr-monitored")
async def get_radarr_monitored(server_id: int | None = Query(default=None)) -> dict:
    radarr_config = _get_radarr_config(server_id)
    if not radarr_config:
        return {"configured": False, "ok": False, "movies": [], "message": "No Radarr server configured"}
    base_url, api_key = radarr_config
    if not api_key:
        return {"configured": False, "ok": False, "movies": [], "message": "Radarr API key missing"}
    try:
        movies = await RadarrClient(base_url=base_url, api_key=api_key, timeout_seconds=settings.source_timeout_seconds).movies()
        items = []
        for m in movies:
            status = str(m.get("status") or "unknown").lower()
            monitored = bool(m.get("monitored"))
            has_file = bool(m.get("hasFile"))
            is_available = bool(m.get("isAvailable"))
            if has_file:
                state_str = "downloaded"
            elif status == "released" and is_available and monitored:
                state_str = "waiting"
            elif monitored:
                state_str = "monitored"
            else:
                state_str = "unmonitored"
            items.append({
                "movie_id": m.get("id"), "tmdb_id": m.get("tmdbId"), "title": m.get("title"),
                "year": m.get("year"), "monitored": monitored, "has_file": has_file, "status": status,
                "is_available": is_available, "state": state_str,
                "digital_release": m.get("digitalRelease"), "physical_release": m.get("physicalRelease"),
                "in_cinemas": m.get("inCinemas"),
            })
        items.sort(key=lambda x: ({"downloaded": 2, "waiting": 0, "monitored": 1, "unmonitored": 3}.get(x["state"], 4), x.get("title") or ""))
        return {"configured": True, "ok": True, "radarr_base_url": settings.radarr_base_url, "movies": items}
    except Exception as exc:
        return {"configured": True, "ok": False, "movies": [], "message": str(exc)}


@router.get("/api/download-health")
async def get_download_health() -> dict:
    if not settings.radarr_api_key:
        return {"configured": False, "ok": False, "message": "Download service API key not configured", "queue_count": 0, "active_count": 0, "download_rate_human": None, "items": []}
    try:
        queue_rows = await RadarrClient(base_url=settings.radarr_base_url, api_key=settings.radarr_api_key, timeout_seconds=settings.source_timeout_seconds).queue_details()
        payload = _build_download_health_payload(queue_rows)
        return {"configured": True, "ok": True, "message": "ok", "radarr_base_url": settings.radarr_base_url, **payload}
    except Exception as exc:
        return {"configured": True, "ok": False, "message": str(exc), "queue_count": 0, "active_count": 0, "download_rate_human": None, "items": []}


@router.get("/api/disk-space")
async def get_disk_space() -> dict:
    disks = []
    seen_sizes: set[int] = set()

    if settings.radarr_api_key:
        try:
            radarr_disks = await RadarrClient(base_url=settings.radarr_base_url, api_key=settings.radarr_api_key, timeout_seconds=settings.source_timeout_seconds).disk_space()
            for d in radarr_disks:
                free_bytes = d.get("freeSpace", 0)
                total_bytes = d.get("totalSpace", 0)
                if total_bytes == 0:
                    continue
                path = d.get("path", "")
                if any(skip in path for skip in ["/System/Volumes", "/private/var", "/AppTranslocation", "/tmp", "/var/folders"]):
                    continue
                if total_bytes in seen_sizes:
                    continue
                seen_sizes.add(total_bytes)
                used_bytes = total_bytes - free_bytes
                percent_used = (used_bytes / total_bytes * 100) if total_bytes > 0 else 0
                label = d.get("label", "") or path
                if label == "/" or not label:
                    label = "Movies Drive"
                disks.append({
                    "path": path, "label": label, "free_bytes": free_bytes, "total_bytes": total_bytes,
                    "used_bytes": used_bytes, "percent_used": round(percent_used, 1),
                    "free_human": _human_size(free_bytes), "total_human": _human_size(total_bytes),
                    "used_human": _human_size(used_bytes), "source": "radarr",
                })
        except Exception as exc:
            logger.warning(f"Failed to get Radarr disk space: {exc}")

    if not disks:
        import shutil
        try:
            usage = shutil.disk_usage("/")
            percent_used = (usage.used / usage.total * 100) if usage.total > 0 else 0
            disks.append({
                "path": "/", "label": "System Drive", "free_bytes": usage.free,
                "total_bytes": usage.total, "used_bytes": usage.used, "percent_used": round(percent_used, 1),
                "free_human": _human_size(usage.free), "total_human": _human_size(usage.total),
                "used_human": _human_size(usage.used), "source": "local",
            })
        except Exception:
            pass

    return {"ok": True, "disks": disks}


@router.get("/api/download-history")
async def get_download_history(limit: int = Query(default=40, ge=1, le=limits.browse_max)) -> dict:
    if not settings.radarr_api_key:
        return {"configured": False, "ok": False, "message": "Download service API key not configured", "items": []}
    try:
        rows = await RadarrClient(base_url=settings.radarr_base_url, api_key=settings.radarr_api_key, timeout_seconds=settings.source_timeout_seconds).history(limit=limit)
        return {"configured": True, "ok": True, "message": "ok", "items": _build_download_history_payload(rows, limit=limit)}
    except Exception as exc:
        return {"configured": True, "ok": False, "message": str(exc), "items": []}


@router.post("/api/download-history/clear")
async def clear_download_history(payload: DownloadHistoryClearRequest) -> dict:
    if not settings.radarr_api_key:
        return {"status": "error", "message": "Download service API key not configured", "auto_download": payload.auto_download, "auto_delete": payload.auto_delete, "grabbed_count": 0, "deleted_count": 0, "queued_count": 0, "cleared_at": datetime.now(UTC).isoformat(), "errors": []}

    client = RadarrClient(base_url=settings.radarr_base_url, api_key=settings.radarr_api_key, timeout_seconds=settings.source_timeout_seconds)
    rows = await client.history(limit=payload.limit)

    grabbed_movie_ids: set[int] = set()
    history_ids: list[int] = []
    for row in rows:
        row_id = row.get("id")
        try:
            if row_id is not None:
                history_ids.append(int(row_id))
        except (TypeError, ValueError):
            pass
        event = str(row.get("eventType") or "").strip().lower()
        if event != "grabbed":
            continue
        movie = row.get("movie") if isinstance(row.get("movie"), dict) else {}
        movie_id = row.get("movieId") or movie.get("id")
        if movie_id is None:
            continue
        try:
            grabbed_movie_ids.add(int(movie_id))
        except (TypeError, ValueError):
            continue

    deleted_count = 0
    errors: list[str] = []
    if payload.auto_delete:
        for history_id in history_ids:
            try:
                await client.delete_history_item(history_id)
                deleted_count += 1
            except Exception as exc:
                errors.append(f"delete:{history_id}: {exc}")

    return {
        "status": "ok", "message": "history clear completed",
        "auto_download": payload.auto_download, "auto_delete": payload.auto_delete,
        "grabbed_count": len(grabbed_movie_ids), "deleted_count": deleted_count,
        "queued_count": 0, "cleared_at": datetime.now(UTC).isoformat(), "errors": errors[:10],
    }


@router.post("/api/download-cancel")
async def cancel_download(payload: DownloadCancelRequest) -> dict:
    if not settings.radarr_api_key:
        return {"ok": False, "message": "Download service API key not configured"}
    try:
        await RadarrClient(base_url=settings.radarr_base_url, api_key=settings.radarr_api_key, timeout_seconds=settings.source_timeout_seconds).remove_queue_item(queue_id=payload.queue_id, remove_from_client=payload.remove_from_client, blocklist=payload.blocklist)
        return {"ok": True, "message": f"Cancelled queue item {payload.queue_id}"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


@router.post("/api/download-cancel-all")
async def cancel_all_downloads() -> dict:
    if not settings.radarr_api_key:
        return {"ok": False, "cancelled": 0, "errors": [], "message": "Download service API key not configured"}
    try:
        client = RadarrClient(base_url=settings.radarr_base_url, api_key=settings.radarr_api_key, timeout_seconds=settings.source_timeout_seconds)
        queue_rows = await client.queue_details()
        cancelled = 0
        errors: list[str] = []
        for row in queue_rows:
            queue_id = row.get("id")
            if queue_id is None:
                continue
            try:
                await client.remove_queue_item(queue_id=int(queue_id), remove_from_client=True, blocklist=False)
                cancelled += 1
            except Exception as exc:
                errors.append(f"queue:{queue_id}: {exc}")
        return {"ok": True, "cancelled": cancelled, "total": len(queue_rows), "errors": errors[:10], "message": f"Cancelled {cancelled}/{len(queue_rows)} queue items"}
    except Exception as exc:
        return {"ok": False, "cancelled": 0, "errors": [str(exc)], "message": str(exc)}


@router.post("/api/monitor")
async def monitor_movie(payload: DownloadMovieRequest) -> dict:
    if not settings.radarr_api_key:
        return {"ok": False, "status": "skipped", "message": "Download service not configured"}
    try:
        result = await RadarrClient(base_url=settings.radarr_base_url, api_key=settings.radarr_api_key, timeout_seconds=settings.source_timeout_seconds).ensure_movie_monitored(title=payload.title, year=payload.year)
        return {"ok": True, **result}
    except Exception as exc:
        return {"ok": False, "status": "error", "message": str(exc)}


@router.post("/api/download")
async def download_movie(payload: DownloadMovieRequest) -> dict:
    if not settings.radarr_api_key:
        return {"ok": False, "status": "skipped", "message": "Download service not configured"}
    try:
        result = await RadarrClient(base_url=settings.radarr_base_url, api_key=settings.radarr_api_key, timeout_seconds=settings.source_timeout_seconds).ensure_movie_wanted(title=payload.title, year=payload.year)
        return {"ok": True, **result}
    except Exception as exc:
        return {"ok": False, "status": "error", "message": str(exc)}


@router.post("/api/download-release")
async def download_specific_release(payload: DownloadReleaseRequest) -> dict:
    import httpx

    if settings.sabnzbd_url and settings.sabnzbd_api_key:
        try:
            sab_url = settings.sabnzbd_url.rstrip("/")
            params = {"mode": "addurl", "name": payload.release_link, "nzbname": payload.raw_title or payload.title, "apikey": settings.sabnzbd_api_key, "cat": "movies", "output": "json"}
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(f"{sab_url}/api", params=params)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status"):
                    if settings.radarr_api_key:
                        try:
                            await RadarrClient(base_url=settings.radarr_base_url, api_key=settings.radarr_api_key, timeout_seconds=5.0).ensure_movie_monitored(title=payload.title, year=payload.year)
                        except Exception:
                            pass
                    short_title = (payload.raw_title or payload.title)[:50]
                    return {"ok": True, "status": "downloading", "message": f"⬇ Downloading: {short_title}..."}
                return {"ok": False, "status": "error", "message": f"SABnzbd error: {data.get('error', 'unknown')}"}
        except Exception as sab_exc:
            return {"ok": False, "status": "error", "message": f"SABnzbd error: {sab_exc}"}

    if settings.radarr_api_key:
        try:
            result = await RadarrClient(base_url=settings.radarr_base_url, api_key=settings.radarr_api_key, timeout_seconds=settings.source_timeout_seconds).ensure_movie_wanted(title=payload.title, year=payload.year)
            return {"ok": True, "status": "queued", "message": "Added to Radarr queue (configure SABNZBD_URL for direct download)", **result}
        except Exception as exc:
            return {"ok": False, "status": "error", "message": str(exc)}

    return {"ok": False, "status": "skipped", "message": "No download service configured. Add SABNZBD_URL and SABNZBD_API_KEY to .env"}
