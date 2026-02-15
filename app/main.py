from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, date, datetime

logger = logging.getLogger(__name__)
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv, set_key
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

from app.agents.criterion_agent import CriterionAgent
from app.agents.drunkenslug_agent import DrunkenSlugAgent
from app.agents.oscar_agent import OscarAgent
from app.agents.plex_agent import PlexAgent
from app.agents.preference_agent import PreferenceAgent
from app.agents.rogerebert_agent import RogerEbertAgent
from app.agents.releases_agent import ReleasesAgent
from app.agents.rottentomatoes_agent import RottenTomatoesAgent
from app.agents.upcoming_agent import UpcomingAgent
from app.agents.usenet_agent import UsenetAgent
from app.clients.ollama_client import OllamaClient
from app.clients.plex_client import PlexClient
from app.clients.poster_lookup_client import PosterLookupClient
from app.clients.radarr_client import RadarrClient
from app.clients.rogerebert_client import RogerEbertClient
from app.clients.releases_client import ReleasesClient
from app.clients.rottentomatoes_client import RottenTomatoesClient
from app.clients.tmdb_client import TMDBClient
from app.clients.usenet_client import UsenetClient
from app.config import settings
from app.models import (
    FeedbackInput,
    FeedbackRow,
    MovieCandidate,
    RecommendationResponse,
    SeenMovieDeleteInput,
    SeenMovieInput,
    SeenMovieRow,
)
from app.auth.dependencies import AdminUser, AuthenticatedUser
from app.auth.router import auth_router, set_memory_store
from app.services.embedding import EmbeddingService
from app.services.llm_explainer import get_explainer
from app.services.memory_store import MemoryStore
from app.services.mood_engine import get_all_moods, get_mood, filter_movies_by_mood, infer_user_moods
from app.services.recommender import Recommender
from app.services.swarm import SwarmOrchestrator

base_dir = Path(__file__).resolve().parent
project_root = base_dir.parent
env_path = project_root / ".env"
env_example_path = project_root / ".env.example"

load_dotenv(dotenv_path=env_path)


DEFAULT_URLS: dict[str, str] = {
    "rottentomatoes_list_url": "https://www.rottentomatoes.com/browse/movies_at_home/sort:popular",
    "releases_url": "https://www.releases.com/calendar/movie",
    "rogerebert_reviews_url": "https://www.rogerebert.com/reviews",
    "plex_base_url": "http://localhost:32400",
    "radarr_base_url": "http://localhost:7878",
    "nzbgeek_rss_url": "https://api.nzbgeek.info/rss?t=search&cat=2000&apikey={API_KEY}",
    "drunkenslug_base_url": "https://drunkenslug.com/api",
    "usenet_base_url": "http://localhost:5076",
    "ollama_base_url": "http://localhost:11434",
    "ollama_model": "llama3.2:1b",
}

REQUIRED_URL_FIELDS = {"plex_base_url", "radarr_base_url", "drunkenslug_base_url", "usenet_base_url", "ollama_base_url"}

ENV_KEY_MAP: dict[str, str] = {
    "google_client_id": "GOOGLE_CLIENT_ID",
    "google_client_secret": "GOOGLE_CLIENT_SECRET",
    "tmdb_api_key": "TMDB_API_KEY",
    "rottentomatoes_list_url": "ROTTENTOMATOES_LIST_URL",
    "releases_url": "RELEASES_URL",
    "rogerebert_reviews_url": "ROGEREBERT_REVIEWS_URL",
    "plex_base_url": "PLEX_BASE_URL",
    "plex_token": "PLEX_TOKEN",
    "radarr_base_url": "RADARR_BASE_URL",
    "radarr_api_key": "RADARR_API_KEY",
    "nzbgeek_rss_url": "NZBGEEK_RSS_URL",
    "nzbgeek_api_key": "NZBGEEK_API_KEY",
    "drunkenslug_base_url": "DRUNKENSLUG_BASE_URL",
    "drunkenslug_api_key": "DRUNKENSLUG_API_KEY",
    "usenet_base_url": "USENET_BASE_URL",
    "usenet_api_key": "USENET_API_KEY",
    "ollama_base_url": "OLLAMA_BASE_URL",
    "ollama_model": "OLLAMA_MODEL",
}

OPTIONAL_FIELDS = {
    "tmdb_api_key",
    "rottentomatoes_list_url",
    "releases_url",
    "rogerebert_reviews_url",
    "plex_token",
    "radarr_api_key",
    "nzbgeek_rss_url",
    "nzbgeek_api_key",
    "drunkenslug_api_key",
    "usenet_api_key",
    "ollama_model",
}


class IntegrationSettingsPayload(BaseModel):
    tmdb_api_key: str | None = None
    rottentomatoes_list_url: str | None = None
    releases_url: str | None = None
    rogerebert_reviews_url: str | None = None
    plex_base_url: str | None = None
    plex_token: str | None = None
    radarr_base_url: str | None = None
    radarr_api_key: str | None = None
    nzbgeek_rss_url: str | None = None
    nzbgeek_api_key: str | None = None
    drunkenslug_base_url: str | None = None
    drunkenslug_api_key: str | None = None
    usenet_base_url: str | None = None
    usenet_api_key: str | None = None
    ollama_base_url: str | None = None
    ollama_model: str | None = None


class IntegrationTestRequest(BaseModel):
    integration: Literal[
        "tmdb",
        "rottentomatoes",
        "releases",
        "rogerebert",
        "plex",
        "radarr",
        "nzbgeek",
        "drunkenslug",
        "usenet",
        "ollama",
    ]
    values: IntegrationSettingsPayload | None = None


class DownloadHistoryClearRequest(BaseModel):
    auto_download: bool = True
    auto_delete: bool = True
    limit: int = 80


class DownloadCancelRequest(BaseModel):
    queue_id: int
    remove_from_client: bool = True
    blocklist: bool = False


class UsenetDownloadItem(BaseModel):
    title: str
    year: int | None = None


class UsenetDownloadBulkRequest(BaseModel):
    items: list[UsenetDownloadItem]


def _ensure_env_file() -> None:
    if env_path.exists():
        return
    if env_example_path.exists():
        env_path.write_text(env_example_path.read_text())
    else:
        env_path.write_text("")


def _to_public_settings_values() -> dict[str, str]:
    return {
        "tmdb_api_key": settings.tmdb_api_key or "",
        "rottentomatoes_list_url": settings.rottentomatoes_list_url or "",
        "releases_url": settings.releases_url or DEFAULT_URLS["releases_url"],
        "rogerebert_reviews_url": settings.rogerebert_reviews_url or "",
        "plex_base_url": settings.plex_base_url or DEFAULT_URLS["plex_base_url"],
        "plex_token": settings.plex_token or "",
        "radarr_base_url": settings.radarr_base_url or DEFAULT_URLS["radarr_base_url"],
        "radarr_api_key": settings.radarr_api_key or "",
        "nzbgeek_rss_url": settings.nzbgeek_rss_url or "",
        "nzbgeek_api_key": settings.nzbgeek_api_key or "",
        "drunkenslug_base_url": settings.drunkenslug_base_url or DEFAULT_URLS["drunkenslug_base_url"],
        "drunkenslug_api_key": settings.drunkenslug_api_key or "",
        "usenet_base_url": settings.usenet_base_url or DEFAULT_URLS["usenet_base_url"],
        "usenet_api_key": settings.usenet_api_key or "",
        "ollama_base_url": settings.ollama_base_url or DEFAULT_URLS["ollama_base_url"],
        "ollama_model": settings.ollama_model or DEFAULT_URLS["ollama_model"],
    }


def _effective_settings_values(overrides: dict[str, str | None] | None = None) -> dict[str, str]:
    values = _to_public_settings_values()
    if not overrides:
        return values

    for field_name, raw_value in overrides.items():
        if field_name not in ENV_KEY_MAP:
            continue
        value = (raw_value or "").strip()
        if field_name in REQUIRED_URL_FIELDS and value == "":
            value = DEFAULT_URLS[field_name]
        values[field_name] = value

    return values


def _set_setting_value(field_name: str, value: str) -> None:
    if field_name in OPTIONAL_FIELDS and value == "":
        setattr(settings, field_name, None)
        return
    setattr(settings, field_name, value)


def _save_settings(payload: dict[str, str | None]) -> None:
    _ensure_env_file()
    for field_name, raw_value in payload.items():
        if field_name not in ENV_KEY_MAP:
            continue
        value = (raw_value or "").strip()

        if field_name in REQUIRED_URL_FIELDS and value == "":
            value = DEFAULT_URLS[field_name]

        set_key(str(env_path), ENV_KEY_MAP[field_name], value, quote_mode="never")
        _set_setting_value(field_name, value)

    load_dotenv(dotenv_path=env_path, override=True)


def _build_runtime() -> tuple[MemoryStore, SwarmOrchestrator]:
    embedding_service = EmbeddingService()
    memory_store = MemoryStore(
        db_path=project_root / settings.memory_db_path,
        embedding_service=embedding_service,
    )

    agents = [
        OscarAgent(
            dataset_path=project_root / "data/oscars_best_picture.json",
            memory_store=memory_store,
        ),
        CriterionAgent(
            dataset_path=project_root / "data/criterion_collection.json",
            memory_store=memory_store,
        ),
        UpcomingAgent(
            tmdb_api_key=settings.tmdb_api_key,
            timeout_seconds=settings.source_timeout_seconds,
            fallback_dataset_path=project_root / "data/upcoming_seed.json",
        ),
        RottenTomatoesAgent(
            list_url=settings.rottentomatoes_list_url,
            timeout_seconds=settings.source_timeout_seconds,
            fallback_dataset_path=project_root / "data/rottentomatoes_seed.json",
        ),
        ReleasesAgent(
            releases_url=settings.releases_url,
            timeout_seconds=settings.source_timeout_seconds,
            fallback_dataset_path=project_root / "data/releases_seed.json",
        ),
        RogerEbertAgent(
            reviews_url=settings.rogerebert_reviews_url,
            timeout_seconds=settings.source_timeout_seconds,
            fallback_dataset_path=project_root / "data/rogerebert_seed.json",
        ),
        PlexAgent(
            base_url=settings.plex_base_url,
            token=settings.plex_token,
            timeout_seconds=settings.source_timeout_seconds,
        ),
        UsenetAgent(
            rss_url=settings.nzbgeek_rss_url,
            api_key=settings.nzbgeek_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        ),
        DrunkenSlugAgent(
            base_url=settings.drunkenslug_base_url,
            api_key=settings.drunkenslug_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        ),
        PreferenceAgent(memory_store=memory_store),
    ]

    recommender = Recommender(memory_store=memory_store)
    poster_lookup_client = PosterLookupClient(
        timeout_seconds=settings.source_timeout_seconds,
        tmdb_api_key=settings.tmdb_api_key,
    )
    tmdb_client = (
        TMDBClient(api_key=settings.tmdb_api_key, timeout_seconds=settings.source_timeout_seconds)
        if settings.tmdb_api_key
        else None
    )
    swarm = SwarmOrchestrator(
        agents=agents,
        recommender=recommender,
        poster_lookup_client=poster_lookup_client,
        tmdb_client=tmdb_client,
    )
    return memory_store, swarm


app = FastAPI(title=settings.app_title)
templates = Jinja2Templates(directory=str(base_dir / "templates"))
app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")

# Include auth router
app.include_router(auth_router)

runtime_lock = asyncio.Lock()
memory_store, swarm = _build_runtime()

# Initialize auth module with memory store
set_memory_store(memory_store)


async def _reload_runtime() -> None:
    global memory_store, swarm
    async with runtime_lock:
        memory_store, swarm = _build_runtime()


async def _ollama_is_connected(base_url: str, model: str) -> bool:
    try:
        client = OllamaClient(
            base_url=base_url,
            model=model,
            timeout_seconds=2.0,
        )
        health = await client.health_check()
        return bool(health.get("ok"))
    except Exception:
        return False


async def _integration_status() -> dict[str, bool]:
    _rss = settings.nzbgeek_rss_url or ""
    _has_placeholder = "{API_KEY}" in _rss or "${API_KEY}" in _rss
    nzbgeek_configured = bool(_rss) and (not _has_placeholder or bool(settings.nzbgeek_api_key))
    ollama_connected = await _ollama_is_connected(
        settings.ollama_base_url,
        settings.ollama_model,
    )
    return {
        "tmdb": bool(settings.tmdb_api_key),
        "rottentomatoes": bool(settings.rottentomatoes_list_url),
        "releases": bool(settings.releases_url),
        "rogerebert": bool(settings.rogerebert_reviews_url),
        "plex": bool(settings.plex_token),
        "radarr": bool(settings.radarr_api_key),
        "nzbgeek": nzbgeek_configured,
        "drunkenslug": bool(settings.drunkenslug_api_key),
        "usenet": bool(settings.usenet_api_key or settings.nzbgeek_api_key or settings.drunkenslug_api_key),
        "ollama": ollama_connected,
    }


def _parse_sources_query(raw_sources: str | None) -> set[str] | None:
    if not raw_sources:
        return None
    parts = {part.strip().lower() for part in raw_sources.split(",") if part.strip()}
    return parts or None


def _normalize_release_date(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        if "T" in value:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None


def _parse_date_query(raw: str | None) -> date | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _movie_source_keys(movie: MovieCandidate, agent_name: str) -> set[str]:
    tags = {tag.lower() for tag in movie.source_tags}
    keys = set(tags)
    keys.add(agent_name.lower())

    if any(tag.startswith("rt-") for tag in tags) or "rottentomatoes" in tags:
        keys.add("rt")
        keys.add("rottentomatoes")
    if "nzbgeek-rss" in tags:
        keys.add("nzbgeek")
    if "drunkenslug" in tags:
        keys.add("drunkenslug")
    if movie.available_on_usenet:
        keys.add("usenet")
    if movie.available_on_plex:
        keys.add("plex")
    if movie.available_on_radarr:
        keys.add("radarr")
    return keys


def _build_release_calendar(
    source_movies: dict[str, list[MovieCandidate]],
    required_sources: set[str] | None = None,
    release_date_from: date | None = None,
    release_date_to: date | None = None,
) -> list[dict]:
    merged: dict[str, dict] = {}
    for agent_name, movies in source_movies.items():
        for movie in movies:
            release_date = _normalize_release_date(movie.release_date)
            if not release_date:
                continue
            release_day = _parse_date_query(release_date)
            if release_day is None:
                continue
            if release_date_from is not None and release_day < release_date_from:
                continue
            if release_date_to is not None and release_day > release_date_to:
                continue

            source_keys = _movie_source_keys(movie, agent_name)
            if required_sources and source_keys.isdisjoint(required_sources):
                continue

            key = f"{movie.title.strip().lower()}::{movie.year if movie.year is not None else 'na'}::{release_date}"
            if key not in merged:
                merged[key] = {
                    "title": movie.title,
                    "year": movie.year,
                    "release_date": release_date,
                    "poster_url": movie.poster_url,
                    "sources": set(source_keys),
                }
            else:
                existing = merged[key]
                existing["sources"] = existing["sources"].union(source_keys)
                if not existing.get("poster_url") and movie.poster_url:
                    existing["poster_url"] = movie.poster_url

    rows = []
    for row in merged.values():
        rows.append(
            {
                "title": row["title"],
                "year": row["year"],
                "release_date": row["release_date"],
                "poster_url": row["poster_url"],
                "sources": sorted(row["sources"]),
            }
        )
    rows.sort(key=lambda item: (item["release_date"], item["title"].lower()))
    return rows


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
    parts = [part for part in value.strip().split(":") if part != ""]
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = [int(part) for part in parts]
    except ValueError:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _human_bytes(value: float | None) -> str | None:
    if value is None:
        return None
    size = float(value)
    if size < 0:
        size = 0
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    return f"{size:.1f} {units[idx]}"


def _build_download_health_payload(queue_rows: list[dict]) -> dict:
    items: list[dict] = []
    total_rate = 0.0

    for row in queue_rows:
        movie = row.get("movie") if isinstance(row.get("movie"), dict) else {}
        title = str(movie.get("title") or row.get("title") or "Unknown title")
        year = movie.get("year")
        status = str(
            row.get("status")
            or row.get("trackedDownloadStatus")
            or row.get("trackedDownloadState")
            or "unknown"
        )
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

        items.append(
            {
                "queue_id": queue_id,
                "movie_id": movie_id,
                "title": title,
                "year": year if isinstance(year, int) else None,
                "status": status,
                "time_left": time_left,
                "progress": round(progress, 1) if progress is not None else None,
                "size_left_human": _human_bytes(size_left),
                "total_size_human": _human_bytes(total_size),
                "rate_human": f"{_human_bytes(rate)}/s" if rate is not None else None,
            }
        )

    active = [
        item
        for item in items
        if any(
            token in item["status"].lower()
            for token in ("downloading", "queued", "delay", "pending", "paused")
        )
    ]
    if not active:
        active = items

    return {
        "queue_count": len(items),
        "active_count": len(active),
        "download_rate_human": f"{_human_bytes(total_rate)}/s" if total_rate > 0 else None,
        "items": active[:25],
    }


def _build_download_history_payload(rows: list[dict], limit: int) -> list[dict]:
    history: list[dict] = []
    for row in rows[:limit]:
        movie = row.get("movie") if isinstance(row.get("movie"), dict) else {}
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        history.append(
            {
                "title": str(movie.get("title") or row.get("sourceTitle") or "Unknown title"),
                "year": movie.get("year") if isinstance(movie.get("year"), int) else None,
                "event": str(row.get("eventType") or "unknown"),
                "timestamp": row.get("date"),
                "download_client": data.get("downloadClient") or data.get("downloadClientName"),
                "source_title": row.get("sourceTitle"),
                "quality": (
                    ((row.get("quality") or {}).get("quality") or {}).get("name")
                    if isinstance(row.get("quality"), dict)
                    else None
                ),
            }
        )
    return history


def _extract_release_title_year(raw_title: str) -> tuple[str, int | None]:
    compact = re.sub(r"[._]", " ", raw_title)
    compact = re.sub(
        r"\b(2160p|1080p|720p|x264|x265|h264|h265|hevc|hdr|webrip|web-dl|bluray|brrip|dvdrip|aac|dts|atmos|proper|repack|extended|criterion)\b",
        "",
        compact,
        flags=re.IGNORECASE,
    )
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", compact)
    year = int(year_match.group(1)) if year_match else None
    if year_match:
        title = compact[: year_match.start()].strip(" -:[]()")
    else:
        title = compact.strip()
    title = re.sub(r"\s+", " ", title).strip()
    return title or raw_title.strip(), year


def _normalize_released_at(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return None


def _release_sort_key(item: dict) -> tuple[int, int]:
    ts = item.get("released_at_iso")
    order = int(item.get("_order", 0))
    if not ts:
        return (0, order)
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (int(dt.timestamp()), order)
    except ValueError:
        return (0, order)


def _matches_usenet_query(item: dict, query: str) -> bool:
    q = query.strip().lower()
    if not q:
        return True
    blob = " ".join(
        str(part)
        for part in [
            item.get("title"),
            item.get("year"),
            item.get("indexer"),
            item.get("release_name"),
            item.get("where_url"),
        ]
        if part is not None
    ).lower()
    return q in blob


async def _enrich_usenet_posters(items: list[dict], max_items: int = 60) -> None:
    if not items:
        return
    poster_client = PosterLookupClient(
        timeout_seconds=settings.source_timeout_seconds,
        tmdb_api_key=settings.tmdb_api_key,
    )
    semaphore = asyncio.Semaphore(8)

    async def enrich(item: dict) -> None:
        async with semaphore:
            try:
                poster = await poster_client.poster_for(item["title"], item.get("year"))
            except Exception:  # noqa: BLE001
                return
            if poster:
                item["poster_url"] = poster

    await asyncio.gather(*(enrich(item) for item in items[:max_items]))


async def _crawl_usenet_releases(limit: int, query: str | None = None) -> dict:
    items: list[dict] = []
    errors: list[str] = []
    indexer_counts: dict[str, int] = {}

    def add_item(
        indexer: str,
        release_name: str,
        where_url: str | None = None,
        released_at: str | None = None,
        details: str | None = None,
    ) -> None:
        title, year = _extract_release_title_year(release_name)
        released_at_iso = _normalize_released_at(released_at)
        items.append(
            {
                "_order": len(items),
                "title": title,
                "year": year,
                "release_name": release_name,
                "indexer": indexer,
                "where_url": where_url,
                "released_at": released_at,
                "released_at_iso": released_at_iso,
                "details": details,
            }
        )
        indexer_counts[indexer] = indexer_counts.get(indexer, 0) + 1

    _rss_url = settings.nzbgeek_rss_url or ""
    _rss_has_placeholder = "{API_KEY}" in _rss_url or "${API_KEY}" in _rss_url
    if _rss_url and (not _rss_has_placeholder or settings.nzbgeek_api_key):
        try:
            logger.info(f"Fetching NZBGeek RSS from: {_rss_url[:50]}...")
            rows = await UsenetClient(
                base_url="https://api.nzbgeek.info",
                api_key=settings.nzbgeek_api_key or "",
                timeout_seconds=settings.source_timeout_seconds,
            ).movie_rss_feed(
                rss_url=settings.nzbgeek_rss_url,
                api_key=settings.nzbgeek_api_key,
            )
            logger.info(f"NZBGeek returned {len(rows)} rows")
            for row in rows:
                raw_title = str(row.get("title") or "").strip()
                if not raw_title:
                    continue
                add_item(
                    indexer="NZBGeek",
                    release_name=raw_title,
                    where_url=row.get("link"),
                    released_at=row.get("pub_date"),
                    details=row.get("description"),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"NZBGeek error: {exc}")
            errors.append(f"NZBGeek: {exc}")

    if settings.drunkenslug_api_key:
        try:
            rows = await UsenetClient(
                base_url=settings.drunkenslug_base_url,
                api_key=settings.drunkenslug_api_key,
                timeout_seconds=settings.source_timeout_seconds,
            ).movie_search(query="")
            for row in rows:
                raw_title = str(row.get("title") or row.get("name") or "").strip()
                if not raw_title:
                    continue
                add_item(
                    indexer="DrunkenSlug",
                    release_name=raw_title,
                    where_url=row.get("link"),
                    released_at=row.get("pubDate") or row.get("pub_date"),
                    details=row.get("description"),
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"DrunkenSlug: {exc}")

    if settings.usenet_api_key:
        try:
            rows = await UsenetClient(
                base_url=settings.usenet_base_url,
                api_key=settings.usenet_api_key,
                timeout_seconds=settings.source_timeout_seconds,
            ).movie_search(query="")
            for row in rows:
                raw_title = str(row.get("title") or row.get("name") or "").strip()
                if not raw_title:
                    continue
                add_item(
                    indexer="Usenet",
                    release_name=raw_title,
                    where_url=row.get("link"),
                    released_at=row.get("pubDate") or row.get("pub_date"),
                    details=row.get("description"),
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Usenet: {exc}")

    rt_scores: dict[str, int] = {}
    if settings.rottentomatoes_list_url:
        try:
            rows = await RottenTomatoesClient(settings.source_timeout_seconds).browse_movies(
                settings.rottentomatoes_list_url
            )
            for row in rows:
                title = row.get("title")
                score = row.get("tomatometer")
                if not title or not isinstance(score, int):
                    continue
                year = row.get("year") if isinstance(row.get("year"), int) else None
                key = f"{str(title).strip().lower()}::{year if year is not None else 'na'}"
                rt_scores[key] = score
        except Exception as exc:  # noqa: BLE001
            errors.append(f"RottenTomatoes: {exc}")

    for item in items:
        key_exact = f"{item['title'].strip().lower()}::{item['year'] if item.get('year') is not None else 'na'}"
        key_fallback = f"{item['title'].strip().lower()}::na"
        score = rt_scores.get(key_exact)
        if score is None:
            score = rt_scores.get(key_fallback)
        item["rottentomatoes_score"] = score

    if query:
        items = [item for item in items if _matches_usenet_query(item, query)]

    await _enrich_usenet_posters(items, max_items=min(limit, 80))
    items.sort(key=lambda item: (-_release_sort_key(item)[0], _release_sort_key(item)[1]))
    public_rows = [
        {key: value for key, value in item.items() if not str(key).startswith("_")}
        for item in items[:limit]
    ]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_items": len(items),
        "indexers": indexer_counts,
        "errors": errors,
        "items": public_rows,
    }


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"app_title": settings.app_title},
    )


@app.get("/integrations", response_class=HTMLResponse)
async def integrations_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="integrations.html",
        context={"app_title": settings.app_title},
    )


@app.get("/usenet", response_class=HTMLResponse)
async def usenet_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="usenet.html",
        context={"app_title": settings.app_title},
    )


@app.get("/api/recommendations", response_model=RecommendationResponse)
async def get_recommendations(
    user_id: str = Query(default="default"),
    count: int = Query(default=200, ge=1, le=1000),
    sort: str | None = Query(default=None),
    sources: str | None = Query(default=None),
    release_from: str | None = Query(default=None),
    release_to: str | None = Query(default=None),
    year_from: int | None = Query(default=None),
    year_to: int | None = Query(default=None),
) -> RecommendationResponse:
    required_sources = _parse_sources_query(sources)
    release_date_from = _parse_date_query(release_from)
    release_date_to = _parse_date_query(release_to)
    if release_date_from and release_date_to and release_date_from > release_date_to:
        release_date_from, release_date_to = release_date_to, release_date_from
    return await swarm.recommend_filtered(
        user_id=user_id,
        count=count,
        sort_mode=sort,
        required_sources=required_sources,
        release_date_from=release_date_from,
        release_date_to=release_date_to,
        year_from=year_from,
        year_to=year_to,
    )


@app.get("/api/moods")
async def get_moods() -> dict:
    """Get all available mood categories."""
    return {"ok": True, "moods": get_all_moods()}


@app.get("/api/moods/infer/{user_id}")
async def infer_moods_for_user(user_id: str) -> dict:
    """Infer mood preferences based on user's feedback history.

    Analyzes the user's liked movies to suggest matching moods.
    """
    try:
        # Get user's feedback history
        feedback_history = await memory.recent_feedback(user_id, limit=50)

        # Convert to format expected by infer_user_moods
        feedback_records = [
            {
                "liked": fb.get("liked", False),
                "genres": fb.get("genres", []),
                "title": fb.get("title", ""),
                "year": fb.get("year"),
            }
            for fb in feedback_history
        ]

        # Infer moods
        suggested_moods = infer_user_moods(feedback_records)

        return {
            "ok": True,
            "user_id": user_id,
            "suggested_moods": suggested_moods,
            "feedback_count": len(feedback_records),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "suggested_moods": [],
        }


@app.get("/api/movies/year/{year}")
async def get_movies_by_year(
    year: int,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Get ALL movies from TMDB for a specific year."""
    if year < 1888 or year > 2030:
        return {"ok": False, "error": "Invalid year", "movies": [], "total": 0}

    # Fetch all movies for year (paginated at TMDB level)
    all_movies = await swarm.fetch_movies_for_year(year, max_pages=10)

    # Apply local pagination
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_movies = all_movies[start_idx:end_idx]

    return {
        "ok": True,
        "year": year,
        "page": page,
        "per_page": per_page,
        "total": len(all_movies),
        "movies": [
            {
                "movie_id": m.movie_id,
                "title": m.title,
                "year": m.year,
                "poster_url": m.poster_url,
                "overview": m.overview,
                "release_date": m.release_date,
                "source_tags": m.source_tags,
                "rottentomatoes_score": m.rottentomatoes_score,
            }
            for m in page_movies
        ],
    }


@app.get("/api/recommendations/mood/{mood_name}")
async def get_mood_recommendations(
    mood_name: str,
    user_id: str = Query(default="default"),
    count: int = Query(default=24, ge=1, le=200),
    year_from: int | None = Query(default=None),
    year_to: int | None = Query(default=None),
) -> dict:
    """Get movie recommendations filtered by mood using LLM."""
    mood = get_mood(mood_name)
    if not mood:
        return {"ok": False, "error": f"Unknown mood: {mood_name}", "recommendations": []}

    # Get base recommendations
    response = await swarm.recommend_filtered(
        user_id=user_id,
        count=min(count * 4, 400),
        sort_mode=None,
        required_sources=None,
        release_date_from=None,
        release_date_to=None,
        year_from=year_from,
        year_to=year_to,
    )

    # Build movie list for LLM analysis
    movie_list = []
    for idx, rec in enumerate(response.recommendations[:100]):  # Limit to 100 for LLM
        movie = rec.movie
        movie_list.append({
            "idx": idx,
            "title": movie.title,
            "year": movie.year,
            "genres": movie.genres,
            "overview": (movie.overview or "")[:200],
            "rec": rec,
        })

    # Use LLM to pick movies matching the mood
    selected_indices = await _llm_filter_by_mood(mood, movie_list, count)

    # Build response from selected movies
    transformed_recommendations: list[dict] = []
    for idx in selected_indices:
        if idx < len(movie_list):
            rec = movie_list[idx]["rec"]
            transformed_recommendations.append({
                "movie": rec.movie.model_dump(),
                "score": float(rec.score),
                "mood_score": 80.0,  # LLM selected = good match
                "reasons": [reason.model_dump() for reason in rec.reasons],
            })

    # If LLM didn't return enough, fall back to strict genre-based filtering
    if len(transformed_recommendations) < count:
        # Use same strict genre requirements as pre-filter
        mood_genre_rules = {
            "funny": {"Comedy"},
            "cozy": {"Comedy", "Drama", "Family", "Romance", "Animation"},
            "romantic": {"Romance"},
            "thrilling": {"Thriller", "Action", "Horror", "Mystery", "Crime"},
            "dark": {"Crime", "Thriller", "Mystery", "Horror"},
            "feel-good": {"Comedy", "Family", "Animation", "Romance"},
            "mind-bending": {"Sci-Fi", "Mystery", "Thriller"},
            "adventurous": {"Adventure", "Action", "Fantasy"},
            "inspiring": {"Drama", "Documentary", "History"},
        }
        required_genres = mood_genre_rules.get(mood_name, set())
        existing_titles = {r["movie"].get("title") for r in transformed_recommendations}

        for rec in response.recommendations:
            if len(transformed_recommendations) >= count:
                break
            movie = rec.movie
            if movie.title in existing_titles:
                continue
            movie_genres = set(movie.genres or [])
            # Must have at least one required genre
            if required_genres and not (movie_genres & required_genres):
                continue
            existing_titles.add(movie.title)
            transformed_recommendations.append({
                "movie": movie.model_dump(),
                "score": float(rec.score),
                "mood_score": 60.0,  # Fallback = lower confidence
                "reasons": [reason.model_dump() for reason in rec.reasons],
            })

    return {
        "ok": True,
        "mood": {
            "name": mood.name,
            "display_name": mood.display_name,
            "emoji": mood.emoji,
            "description": mood.description,
        },
        "recommendations": transformed_recommendations[:count],
        "total": len(transformed_recommendations),
    }


def _prefilter_by_mood_genres(movie_list: list[dict], mood_name: str) -> list[dict]:
    """Pre-filter movies by genre to help LLM make better selections."""
    # Define which genres are REQUIRED/PREFERRED/AVOIDED for each mood
    # require: at least one of these genres must be present
    # prefer: extra weight for these genres
    # avoid: exclude movies with these genres
    mood_genre_rules = {
        "cozy": {
            "require": {"Comedy", "Drama", "Family", "Romance", "Animation", "Music"},
            "prefer": {"Comedy", "Family", "Romance", "Animation"},
            "avoid": {"Horror", "Thriller", "War", "Crime", "Action"},
        },
        "funny": {
            "require": {"Comedy"},  # MUST have Comedy
            "prefer": {"Comedy"},
            "avoid": {"Horror", "Thriller", "War", "Crime", "Drama"},
        },
        "thrilling": {
            "require": {"Thriller", "Action", "Horror", "Mystery", "Crime"},
            "prefer": {"Thriller", "Action", "Horror"},
            "avoid": {"Comedy", "Family", "Animation", "Romance", "Music"},
        },
        "romantic": {
            "require": {"Romance"},
            "prefer": {"Romance", "Drama"},
            "avoid": {"Horror", "Action", "War", "Crime", "Thriller"},
        },
        "dark": {
            "require": {"Crime", "Thriller", "Mystery", "Drama", "Horror"},
            "prefer": {"Crime", "Thriller", "Horror"},
            "avoid": {"Comedy", "Family", "Animation", "Music"},
        },
        "feel-good": {
            "require": {"Comedy", "Family", "Animation", "Music", "Romance"},
            "prefer": {"Comedy", "Family", "Animation"},
            "avoid": {"Horror", "Thriller", "War", "Crime"},
        },
        "mind-bending": {
            "require": {"Sci-Fi", "Mystery", "Thriller"},
            "prefer": {"Sci-Fi", "Mystery"},
            "avoid": {"Comedy", "Family", "Animation", "Romance"},
        },
        "nostalgic": {
            "require": set(),  # No genre requirement
            "prefer": set(),
            "avoid": set(),
        },
        "adventurous": {
            "require": {"Adventure", "Action", "Fantasy", "Sci-Fi"},
            "prefer": {"Adventure", "Fantasy"},
            "avoid": {"Documentary"},
        },
        "inspiring": {
            "require": {"Drama", "Documentary", "History"},
            "prefer": {"Drama", "History"},
            "avoid": {"Horror", "Crime"},
        },
    }

    rules = mood_genre_rules.get(mood_name, {"require": set(), "prefer": set(), "avoid": set()})
    require_genres = rules.get("require", set())
    prefer_genres = rules.get("prefer", set())
    avoid_genres = rules.get("avoid", set())

    # STRICT filtering: only include movies that match required genres
    filtered = []
    for m in movie_list:
        genres = set(m.get("genres", []))
        if not genres:
            continue  # Skip movies without genre info
        # MUST have at least one required genre
        if require_genres and not (genres & require_genres):
            continue
        # MUST NOT have avoided genres (strict for moods like "funny")
        if avoid_genres and (genres & avoid_genres):
            continue
        filtered.append(m)

    # Only relax if we have almost nothing
    if len(filtered) < 5:
        # Relax: allow avoided genres but still require preferred genres
        filtered = []
        for m in movie_list:
            genres = set(m.get("genres", []))
            if not genres:
                continue
            if require_genres and not (genres & require_genres):
                continue
            filtered.append(m)

    # Sort by preference score (more preferred genres = higher score)
    def score_movie(m):
        genres = set(m.get("genres", []))
        return len(genres & prefer_genres) * 2 - len(genres & avoid_genres)

    filtered.sort(key=score_movie, reverse=True)
    return filtered


async def _llm_filter_by_mood(mood, movie_list: list[dict], count: int) -> list[int]:
    """Use LLM to select movies that match the mood."""
    if not settings.ollama_base_url or not movie_list:
        return []

    # Pre-filter by genre to give LLM better candidates
    prefiltered = _prefilter_by_mood_genres(movie_list, mood.name)

    # Build a detailed movie list with overviews for better context
    movies_text_parts = []
    idx_map = {}  # Map prompt indices to original indices
    for prompt_idx, m in enumerate(prefiltered[:50]):  # Limit for prompt size
        genres = ', '.join(m['genres'][:3]) if m['genres'] else 'Unknown'
        overview = m['overview'][:120] + '...' if len(m['overview']) > 120 else m['overview']
        movies_text_parts.append(
            f"{prompt_idx}. {m['title']} ({m['year'] or '?'}) [{genres}] - {overview or 'No description'}"
        )
        idx_map[prompt_idx] = m['idx']
    movies_text = "\n".join(movies_text_parts)

    # Define what each mood means for better filtering
    mood_hints = {
        "cozy": "Select ONLY feel-good, heartwarming movies. Comedy, family, romance films. NO thrillers, horror, crime, or tense films.",
        "funny": "Select ONLY pure comedies. Movies that are genuinely funny and make people laugh. NO dramas, thrillers, or horror.",
        "thrilling": "Select suspenseful, tense films. Action, horror, mystery, crime thrillers.",
        "romantic": "Select love stories and romantic films. Romance, romantic comedies, relationship dramas.",
        "dark": "Select dark, intense films. Crime, noir, psychological thrillers, gritty dramas.",
        "feel-good": "Select uplifting, happy movies. Inspiring stories with positive endings. NO sad or dark films.",
        "mind-bending": "Select complex, twist-filled films. Sci-fi puzzles, psychological mysteries.",
        "nostalgic": "Select beloved classics and older films with retro charm.",
        "adventurous": "Select epic journeys and adventures. Fantasy, exploration, action adventures.",
        "inspiring": "Select triumph stories about overcoming odds. Biographical successes, sports victories.",
    }
    hint = mood_hints.get(mood.name, "")

    prompt = f"""Select {count} movies that perfectly match "{mood.display_name}" mood.

{hint}

Movie list:
{movies_text}

Reply with ONLY the numbers of your selections, separated by commas.
Example: 0, 3, 7, 12

Selected movies:"""

    try:
        # Use larger model if available
        model = "llama3.1:8b" if "llama3.1:8b" in settings.ollama_model or settings.ollama_model == "llama3.2:1b" else settings.ollama_model
        client = OllamaClient(
            base_url=settings.ollama_base_url,
            model=model,
            timeout_seconds=45.0,
        )
        response = await client.generate(
            prompt=prompt,
            system="You are a movie expert. Output only comma-separated numbers. No explanations.",
        )

        # Parse the response to extract indices
        indices = []
        # Clean response - extract just numbers
        clean_response = ''.join(c if c.isdigit() or c in ', \n' else ' ' for c in response)
        for part in clean_response.replace("\n", ",").split(","):
            part = part.strip()
            if part.isdigit():
                prompt_idx = int(part)
                # Map prompt index back to original index
                if prompt_idx in idx_map:
                    original_idx = idx_map[prompt_idx]
                    if original_idx not in indices:
                        indices.append(original_idx)
                        if len(indices) >= count:
                            break
        return indices
    except Exception as exc:
        logger.warning(f"LLM mood filter failed: {exc}")
        return []


@app.get("/api/release-calendar")
async def get_release_calendar(
    user_id: str = Query(default="default"),
    sources: str | None = Query(default=None),
    release_from: str | None = Query(default=None),
    release_to: str | None = Query(default=None),
    limit: int = Query(default=1500, ge=1, le=5000),
) -> dict:
    required_sources = _parse_sources_query(sources)
    release_date_from = _parse_date_query(release_from)
    release_date_to = _parse_date_query(release_to)
    if release_date_from and release_date_to and release_date_from > release_date_to:
        release_date_from, release_date_to = release_date_to, release_date_from
    source_movies, _agent_statuses = await swarm.collect_sources(user_id=user_id, count=120)
    source_movies.pop("radarr", None)
    rows = _build_release_calendar(
        source_movies,
        required_sources=required_sources,
        release_date_from=release_date_from,
        release_date_to=release_date_to,
    )
    source_counts: dict[str, int] = {}
    for row in rows:
        for source in row["sources"]:
            source_counts[source] = source_counts.get(source, 0) + 1
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_items": len(rows),
        "source_counts": source_counts,
        "items": rows[:limit],
    }


@app.get("/api/usenet/releases")
async def get_usenet_releases(
    limit: int = Query(default=250, ge=1, le=2000),
    q: str | None = Query(default=None),
) -> dict:
    return await _crawl_usenet_releases(limit=limit, query=q)


async def _fetch_nzbgeek_movies(limit: int = 100) -> list[dict]:
    """Fetch new movie releases from NZBGeek using the dedicated new_movies RSS feed."""
    # Get API key from settings - try to extract from RSS URL if not set directly
    api_key = settings.nzbgeek_api_key or ""
    if not api_key and settings.nzbgeek_rss_url:
        # Try to extract apikey or r= param from URL
        match = re.search(r'(?:apikey|r)=([^&]+)', settings.nzbgeek_rss_url)
        if match:
            api_key = match.group(1)

    if not api_key:
        return []

    # Use NZBGeek's dedicated new_movies RSS feed - this is the same as geekseek.php?new_movies
    movies_url = f"https://api.nzbgeek.info/rss?t=new_movies&limit={limit}&r={api_key}"

    try:
        client = UsenetClient(
            base_url="https://api.nzbgeek.info",
            api_key=api_key,
            timeout_seconds=settings.source_timeout_seconds,
        )
        rows = await client.movie_rss_feed(rss_url=movies_url, api_key=api_key)
        return rows
    except Exception as exc:
        logger.warning(f"Failed to fetch NZBGeek movies: {exc}")
        return []


@app.get("/api/usenet/latest")
async def get_usenet_latest(
    limit: int = Query(default=12, ge=1, le=50),
) -> dict:
    """Get the latest new movie releases from NZBGeek's new_movies feed."""
    try:
        # Fetch from NZBGeek's dedicated new_movies RSS feed
        raw_movies = await _fetch_nzbgeek_movies(limit=limit * 3)

        if not raw_movies:
            # Fallback to crawl if direct fetch fails
            data = await _crawl_usenet_releases(limit=limit * 2, query=None)
            raw_movies = data.get("items", [])

        # Create poster client for enrichment
        _poster_client = None
        if settings.tmdb_api_key:
            _poster_client = PosterLookupClient(
                timeout_seconds=settings.source_timeout_seconds,
                tmdb_api_key=settings.tmdb_api_key,
            )

        # Enrich with posters from TMDB
        enriched = []
        seen_titles = set()
        for r in raw_movies:
            raw_title = r.get("title", "")
            if not raw_title:
                continue

            # Parse title and year from release name
            title, year = _extract_release_title_year(raw_title)

            # Dedupe by title
            title_key = title.lower()
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)

            poster_url = None
            overview = ""

            # Try to get poster from TMDB
            if _poster_client and title:
                try:
                    info = await _poster_client.lookup(title, year)
                    if info:
                        poster_url = info.get("poster_url")
                        overview = info.get("overview", "")
                except Exception:
                    pass

            enriched.append({
                "title": title,
                "year": year,
                "poster_url": poster_url,
                "overview": overview,
                "quality": "",
                "size": "",
                "source": "nzbgeek",
                "pub_date": r.get("pub_date", ""),
                "release_name": raw_title,
            })

            if len(enriched) >= limit:
                break

        return {"ok": True, "releases": enriched, "count": len(enriched)}
    except Exception as exc:
        logger.warning(f"Failed to get latest usenet: {exc}")
        return {"ok": False, "releases": [], "error": str(exc)}


@app.get("/api/trailer")
async def get_trailer(title: str = Query(...), year: int | None = Query(default=None)) -> dict:
    if not settings.tmdb_api_key:
        return {"ok": False, "video_key": None, "message": "TMDB not configured"}
    try:
        tmdb = TMDBClient(api_key=settings.tmdb_api_key, timeout_seconds=settings.source_timeout_seconds)
        results = await tmdb.search_movie(query=title.strip(), year=year)
        if not results:
            return {"ok": False, "video_key": None, "message": "Movie not found"}
        tmdb_id = results[0].get("id")
        if not tmdb_id:
            return {"ok": False, "video_key": None, "message": "No TMDB ID"}
        videos = await tmdb.movie_videos(tmdb_id)
        for v in videos:
            if v.get("site", "").lower() == "youtube" and v.get("type", "").lower() == "trailer":
                return {"ok": True, "video_key": v["key"]}
        for v in videos:
            if v.get("site", "").lower() == "youtube" and v.get("type", "").lower() == "teaser":
                return {"ok": True, "video_key": v["key"]}
        for v in videos:
            if v.get("site", "").lower() == "youtube":
                return {"ok": True, "video_key": v["key"]}
        return {"ok": False, "video_key": None, "message": "No YouTube trailer found"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "video_key": None, "message": str(exc)}


@app.get("/api/search")
async def search_movies(q: str = Query(..., min_length=1)) -> dict:
    if not settings.tmdb_api_key:
        return {"ok": False, "results": [], "message": "TMDB not configured"}

    try:
        tmdb = TMDBClient(api_key=settings.tmdb_api_key, timeout_seconds=settings.source_timeout_seconds)
        raw = await tmdb.search_movie(query=q.strip())
        results = []
        for m in raw[:20]:
            poster_path = m.get("poster_path")
            poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
            backdrop_path = m.get("backdrop_path")
            backdrop_url = f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else None
            release = m.get("release_date") or ""
            year = int(release[:4]) if len(release) >= 4 else None
            results.append({
                "tmdb_id": m.get("id"),
                "title": m.get("title"),
                "year": year,
                "overview": m.get("overview", ""),
                "poster_url": poster_url,
                "backdrop_url": backdrop_url,
                "vote_average": m.get("vote_average"),
                "release_date": release,
            })
        return {"ok": True, "results": results}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "results": [], "message": str(exc)}


@app.get("/api/radarr-monitored")
async def get_radarr_monitored() -> dict:
    if not settings.radarr_api_key:
        return {"configured": False, "ok": False, "movies": [], "message": "Download service not configured"}

    try:
        movies = await RadarrClient(
            base_url=settings.radarr_base_url,
            api_key=settings.radarr_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        ).movies()

        items = []
        for m in movies:
            status = str(m.get("status") or "unknown").lower()
            monitored = bool(m.get("monitored"))
            has_file = bool(m.get("hasFile"))
            is_available = bool(m.get("isAvailable"))

            if has_file:
                state = "downloaded"
            elif status == "released" and is_available and monitored:
                state = "waiting"
            elif monitored:
                state = "monitored"
            else:
                state = "unmonitored"

            items.append({
                "movie_id": m.get("id"),
                "title": m.get("title"),
                "year": m.get("year"),
                "monitored": monitored,
                "has_file": has_file,
                "status": status,
                "is_available": is_available,
                "state": state,
                "digital_release": m.get("digitalRelease"),
                "physical_release": m.get("physicalRelease"),
                "in_cinemas": m.get("inCinemas"),
            })

        items.sort(key=lambda x: (
            {"downloaded": 2, "waiting": 0, "monitored": 1, "unmonitored": 3}.get(x["state"], 4),
            x.get("title") or "",
        ))

        return {"configured": True, "ok": True, "radarr_base_url": settings.radarr_base_url, "movies": items}
    except Exception as exc:  # noqa: BLE001
        return {"configured": True, "ok": False, "movies": [], "message": str(exc)}


@app.get("/api/download-health")
async def get_download_health() -> dict:
    if not settings.radarr_api_key:
        return {
            "configured": False,
            "ok": False,
            "message": "Download service API key not configured",
            "queue_count": 0,
            "active_count": 0,
            "download_rate_human": None,
            "items": [],
        }

    try:
        queue_rows = await RadarrClient(
            base_url=settings.radarr_base_url,
            api_key=settings.radarr_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        ).queue_details()
        payload = _build_download_health_payload(queue_rows)
        return {"configured": True, "ok": True, "message": "ok", "radarr_base_url": settings.radarr_base_url, **payload}
    except Exception as exc:  # noqa: BLE001
        return {
            "configured": True,
            "ok": False,
            "message": str(exc),
            "queue_count": 0,
            "active_count": 0,
            "download_rate_human": None,
            "items": [],
        }


@app.get("/api/disk-space")
async def get_disk_space() -> dict:
    """Get disk space info from Radarr or local system."""
    disks = []
    seen_sizes = set()

    # Try to get disk space from Radarr first (shows where movies are stored)
    if settings.radarr_api_key:
        try:
            client = RadarrClient(
                base_url=settings.radarr_base_url,
                api_key=settings.radarr_api_key,
                timeout_seconds=settings.source_timeout_seconds,
            )
            radarr_disks = await client.disk_space()
            for d in radarr_disks:
                free_bytes = d.get("freeSpace", 0)
                total_bytes = d.get("totalSpace", 0)

                # Skip empty or system volumes
                if total_bytes == 0:
                    continue
                path = d.get("path", "")
                # Skip macOS system paths
                if any(skip in path for skip in [
                    "/System/Volumes",
                    "/private/var",
                    "/AppTranslocation",
                    "/tmp",
                    "/var/folders",
                ]):
                    continue

                # Dedupe by total size (same physical disk)
                size_key = total_bytes
                if size_key in seen_sizes:
                    continue
                seen_sizes.add(size_key)

                used_bytes = total_bytes - free_bytes
                percent_used = (used_bytes / total_bytes * 100) if total_bytes > 0 else 0

                # Clean up label
                label = d.get("label", "") or path
                if label == "/" or not label:
                    label = "Movies Drive"

                disks.append({
                    "path": path,
                    "label": label,
                    "free_bytes": free_bytes,
                    "total_bytes": total_bytes,
                    "used_bytes": used_bytes,
                    "percent_used": round(percent_used, 1),
                    "free_human": _human_size(free_bytes),
                    "total_human": _human_size(total_bytes),
                    "used_human": _human_size(used_bytes),
                    "source": "radarr",
                })
        except Exception as exc:
            logger.warning(f"Failed to get Radarr disk space: {exc}")

    # Fallback to local disk space if no Radarr data
    if not disks:
        import shutil
        try:
            usage = shutil.disk_usage("/")
            percent_used = (usage.used / usage.total * 100) if usage.total > 0 else 0
            disks.append({
                "path": "/",
                "label": "System Drive",
                "free_bytes": usage.free,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "percent_used": round(percent_used, 1),
                "free_human": _human_size(usage.free),
                "total_human": _human_size(usage.total),
                "used_human": _human_size(usage.used),
                "source": "local",
            })
        except Exception:
            pass

    return {"ok": True, "disks": disks}


def _human_size(bytes_val: int) -> str:
    """Convert bytes to human readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(bytes_val) < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} PB"


@app.get("/api/download-history")
async def get_download_history(limit: int = Query(default=40, ge=1, le=200)) -> dict:
    if not settings.radarr_api_key:
        return {
            "configured": False,
            "ok": False,
            "message": "Download service API key not configured",
            "items": [],
        }

    try:
        rows = await RadarrClient(
            base_url=settings.radarr_base_url,
            api_key=settings.radarr_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        ).history(limit=limit)
        return {
            "configured": True,
            "ok": True,
            "message": "ok",
            "items": _build_download_history_payload(rows, limit=limit),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "configured": True,
            "ok": False,
            "message": str(exc),
            "items": [],
        }


@app.post("/api/download-history/clear")
async def clear_download_history(payload: DownloadHistoryClearRequest) -> dict:
    if not settings.radarr_api_key:
        return {
            "status": "error",
            "message": "Download service API key not configured",
            "auto_download": payload.auto_download,
            "auto_delete": payload.auto_delete,
            "grabbed_count": 0,
            "deleted_count": 0,
            "queued_count": 0,
            "cleared_at": datetime.now(UTC).isoformat(),
            "errors": [],
        }

    client = RadarrClient(
        base_url=settings.radarr_base_url,
        api_key=settings.radarr_api_key,
        timeout_seconds=settings.source_timeout_seconds,
    )
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
    queued_count = 0
    errors: list[str] = []
    if payload.auto_delete:
        for history_id in history_ids:
            try:
                await client.delete_history_item(history_id)
                deleted_count += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"delete:{history_id}: {exc}")

    # auto_download disabled — never re-trigger downloads automatically

    return {
        "status": "ok",
        "message": "history clear completed",
        "auto_download": payload.auto_download,
        "auto_delete": payload.auto_delete,
        "grabbed_count": len(grabbed_movie_ids),
        "deleted_count": deleted_count,
        "queued_count": queued_count,
        "cleared_at": datetime.now(UTC).isoformat(),
        "errors": errors[:10],
    }


@app.post("/api/download-cancel")
async def cancel_download(payload: DownloadCancelRequest) -> dict:
    if not settings.radarr_api_key:
        return {"ok": False, "message": "Download service API key not configured"}

    try:
        client = RadarrClient(
            base_url=settings.radarr_base_url,
            api_key=settings.radarr_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        )
        await client.remove_queue_item(
            queue_id=payload.queue_id,
            remove_from_client=payload.remove_from_client,
            blocklist=payload.blocklist,
        )
        return {"ok": True, "message": f"Cancelled queue item {payload.queue_id}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc)}


@app.post("/api/download-cancel-all")
async def cancel_all_downloads() -> dict:
    if not settings.radarr_api_key:
        return {"ok": False, "cancelled": 0, "errors": [], "message": "Download service API key not configured"}

    try:
        client = RadarrClient(
            base_url=settings.radarr_base_url,
            api_key=settings.radarr_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        )
        queue_rows = await client.queue_details()
        cancelled = 0
        errors: list[str] = []
        for row in queue_rows:
            queue_id = row.get("id")
            if queue_id is None:
                continue
            try:
                await client.remove_queue_item(
                    queue_id=int(queue_id),
                    remove_from_client=True,
                    blocklist=False,
                )
                cancelled += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"queue:{queue_id}: {exc}")
        return {
            "ok": True,
            "cancelled": cancelled,
            "total": len(queue_rows),
            "errors": errors[:10],
            "message": f"Cancelled {cancelled}/{len(queue_rows)} queue items",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "cancelled": 0, "errors": [str(exc)], "message": str(exc)}


@app.post("/api/feedback")
async def post_feedback(payload: FeedbackInput) -> dict:
    await memory_store.add_feedback(payload)
    category = "watch" if payload.liked else "skipped"
    memory_store.upsert_seen(
        SeenMovieInput(
            user_id=payload.user_id,
            movie_id=payload.movie_id,
            title=payload.title,
            year=payload.year,
            source=category,
        )
    )

    return {"status": "ok", "seen_source": category}


class DownloadMovieRequest(BaseModel):
    title: str
    year: int | None = None


@app.post("/api/monitor")
async def monitor_movie(payload: DownloadMovieRequest) -> dict:
    if not settings.radarr_api_key:
        return {"ok": False, "status": "skipped", "message": "Download service not configured"}
    try:
        result = await RadarrClient(
            base_url=settings.radarr_base_url,
            api_key=settings.radarr_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        ).ensure_movie_monitored(title=payload.title, year=payload.year)
        return {"ok": True, **result}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "error", "message": str(exc)}


@app.post("/api/download")
async def download_movie(payload: DownloadMovieRequest) -> dict:
    if not settings.radarr_api_key:
        return {"ok": False, "status": "skipped", "message": "Download service not configured"}

    try:
        result = await RadarrClient(
            base_url=settings.radarr_base_url,
            api_key=settings.radarr_api_key,
            timeout_seconds=settings.source_timeout_seconds,
        ).ensure_movie_wanted(title=payload.title, year=payload.year)
        return {"ok": True, **result}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "error", "message": str(exc)}


@app.get("/api/feedback/{user_id}", response_model=list[FeedbackRow])
async def get_feedback(user_id: str) -> list[FeedbackRow]:
    return memory_store.recent_feedback(user_id=user_id, limit=100)


@app.get("/api/seen/{user_id}", response_model=list[SeenMovieRow])
async def get_seen_movies(
    user_id: str,
    limit: int = Query(default=500, ge=1, le=2000),
    q: str | None = Query(default=None),
) -> list[SeenMovieRow]:
    return memory_store.list_seen(user_id=user_id, limit=limit, query=q)


@app.post("/api/seen")
async def add_seen_movie(payload: SeenMovieInput) -> dict:
    memory_store.upsert_seen(payload)
    return {"status": "ok"}


@app.delete("/api/seen")
async def remove_seen_movie(payload: SeenMovieDeleteInput) -> dict:
    removed = memory_store.remove_seen(user_id=payload.user_id, movie_id=payload.movie_id)
    return {"status": "ok", "removed": removed}


@app.post("/api/seen/import/plex")
async def import_seen_from_plex(
    user_id: str = Query(default="default"),
) -> dict:
    if not settings.plex_token:
        return {"ok": False, "imported": 0, "message": "PLEX_TOKEN missing"}

    rows = await PlexClient(
        base_url=settings.plex_base_url,
        token=settings.plex_token,
        timeout_seconds=settings.source_timeout_seconds,
    ).library_movies()

    imported = 0
    for row in rows:
        title = row.get("title")
        if not title:
            continue
        rating_key = row.get("ratingKey")
        year = row.get("year")
        movie_id = (
            f"plex:{rating_key}"
            if rating_key
            else f"plex:{title.strip().lower().replace(' ', '_')}::{year if year is not None else 'na'}"
        )
        memory_store.upsert_seen(
            SeenMovieInput(
                user_id=user_id,
                movie_id=movie_id,
                title=title,
                year=year,
                source="plex",
            )
        )
        imported += 1

    return {
        "ok": True,
        "imported": imported,
        "total": len(rows),
        "message": f"Imported {imported} movies from Plex library",
    }


@app.get("/api/plex/library")
async def plex_library(
    limit: int = Query(default=600, ge=1, le=2000),
    q: str | None = Query(default=None),
) -> dict:
    if not settings.plex_token:
        return {"ok": False, "movies": [], "message": "PLEX_TOKEN missing"}

    rows = await PlexClient(
        base_url=settings.plex_base_url,
        token=settings.plex_token,
        timeout_seconds=settings.source_timeout_seconds,
    ).library_movies()

    query = (q or "").strip().lower()
    movies: list[dict] = []
    for row in rows:
        title = row.get("title")
        if not title:
            continue
        if query and query not in title.lower():
            continue
        year = row.get("year")
        rating_key = row.get("ratingKey")
        movie_id = (
            f"plex:{rating_key}"
            if rating_key
            else f"plex:{title.strip().lower().replace(' ', '_')}::{year if year is not None else 'na'}"
        )
        movies.append(
            {
                "movie_id": movie_id,
                "title": title,
                "year": year,
            }
        )

    movies.sort(key=lambda row: (row["title"].lower(), row.get("year") or 0))
    return {"ok": True, "total": len(movies), "movies": movies[:limit]}


class AIChatRequest(BaseModel):
    message: str
    context: str | None = None


class AIChatResponse(BaseModel):
    response: str
    sources_queried: list[str] = Field(default_factory=list)


async def _query_usenet_sources(query: str) -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {}

    if settings.drunkenslug_api_key:
        try:
            client = UsenetClient(
                base_url=settings.drunkenslug_base_url,
                api_key=settings.drunkenslug_api_key,
                timeout_seconds=settings.source_timeout_seconds,
            )
            rows = await client.movie_search(query=query)
            results["drunkenslug"] = rows[:10]
        except Exception:
            results["drunkenslug"] = []

    if settings.nzbgeek_api_key and settings.nzbgeek_rss_url:
        try:
            client = UsenetClient(
                base_url="https://api.nzbgeek.info",
                api_key=settings.nzbgeek_api_key,
                timeout_seconds=settings.source_timeout_seconds,
            )
            rows = await client.movie_search(query=query)
            results["nzbgeek"] = rows[:10]
        except Exception:
            results["nzbgeek"] = []

    if settings.usenet_api_key:
        try:
            client = UsenetClient(
                base_url=settings.usenet_base_url,
                api_key=settings.usenet_api_key,
                timeout_seconds=settings.source_timeout_seconds,
            )
            rows = await client.movie_search(query=query)
            results["usenet"] = rows[:10]
        except Exception:
            results["usenet"] = []

    return results


def _format_usenet_results(results: dict[str, list[dict]]) -> str:
    if not any(results.values()):
        return "No results found from any usenet source."

    parts = []
    for source, rows in results.items():
        if rows:
            titles = [f"- {r.get('title', 'Unknown')} ({r.get('size', 'N/A')})" for r in rows[:5]]
            parts.append(f"**{source.title()}** ({len(rows)} results):\n" + "\n".join(titles))
        else:
            parts.append(f"**{source.title()}**: No results")
    return "\n\n".join(parts)


@app.post("/api/ai/chat")
async def ai_chat(payload: AIChatRequest) -> AIChatResponse:
    if not settings.ollama_base_url:
        return AIChatResponse(
            response="Ollama is not configured. Please set up Ollama in Settings.",
            sources_queried=[],
        )

    message = payload.message.strip()
    sources_queried: list[str] = []

    search_terms = None
    search_keywords = ["search", "find", "look for", "looking for", "any", "have you got", "do you have", "what about"]
    provider_keywords = ["drunkenslug", "nzbgeek", "usenet", "nzb", "indexer"]

    message_lower = message.lower()
    is_search_query = any(kw in message_lower for kw in search_keywords)
    mentions_provider = any(kw in message_lower for kw in provider_keywords)

    if is_search_query or mentions_provider:
        words = message.split()
        stop_words = {"hey", "hi", "hello", "drunkenslug", "nzbgeek", "usenet", "can", "you", "do", "have", "any", "search", "find", "for", "the", "a", "an", "is", "there", "what", "about", "got", "looking"}
        search_terms = " ".join([w for w in words if w.lower().strip("?,!.") not in stop_words])

    usenet_context = ""
    if search_terms:
        usenet_results = await _query_usenet_sources(search_terms)
        sources_queried = [k for k, v in usenet_results.items() if v]
        usenet_context = _format_usenet_results(usenet_results)

    system_prompt = """You are a helpful movie assistant for the Majic Movie Selector app.
You can help users find movies on usenet indexers like DrunkenSlug, NZBGeek, and other Newznab sources.
When users ask about movie availability, you'll receive search results from the configured indexers.
Be friendly and conversational. If you have search results, summarize them helpfully.
If no results were found, suggest the user try different search terms or check their indexer configuration."""

    user_prompt = message
    if usenet_context:
        user_prompt = f"""User question: {message}

Here are the search results from the usenet indexers:

{usenet_context}

Please respond to the user's question based on these results."""

    try:
        client = OllamaClient(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout_seconds=30.0,
        )
        response = await client.generate(prompt=user_prompt, system=system_prompt)
        return AIChatResponse(response=response, sources_queried=sources_queried)
    except Exception as exc:
        return AIChatResponse(
            response=f"Sorry, I couldn't connect to Ollama: {exc}",
            sources_queried=sources_queried,
        )


@app.get("/api/integrations")
async def integration_status() -> dict:
    return await _integration_status()


@app.get("/api/ollama/models")
async def list_ollama_models() -> dict:
    if not settings.ollama_base_url:
        return {"ok": False, "models": [], "message": "Ollama not configured"}
    try:
        client = OllamaClient(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout_seconds=10.0,
        )
        models = await client.list_models()
        return {
            "ok": True,
            "models": models,
            "current_model": settings.ollama_model,
        }
    except Exception as exc:
        return {"ok": False, "models": [], "message": str(exc)}


class OllamaPullRequest(BaseModel):
    model: str


@app.post("/api/ollama/pull")
async def pull_ollama_model(payload: OllamaPullRequest, user: AdminUser) -> dict:
    if not settings.ollama_base_url:
        return {"ok": False, "message": "Ollama not configured"}

    import httpx

    model_name = payload.model.strip()
    if not model_name:
        return {"ok": False, "message": "Model name required"}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            response = await client.post(
                f"{settings.ollama_base_url}/api/pull",
                json={"name": model_name, "stream": False},
            )
            if response.status_code == 200:
                return {"ok": True, "message": f"Model '{model_name}' pulled successfully"}
            else:
                return {"ok": False, "message": f"Failed to pull: {response.text}"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


@app.get("/api/settings")
async def get_settings() -> dict:
    return {"values": _to_public_settings_values(), "defaults": DEFAULT_URLS}


@app.post("/api/settings")
async def save_settings(payload: IntegrationSettingsPayload) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    if updates:
        _save_settings(updates)
        await _reload_runtime()
    return {
        "status": "ok",
        "integrations": await _integration_status(),
        "values": _to_public_settings_values(),
    }


@app.post("/api/integrations/test")
async def test_integration(payload: IntegrationTestRequest) -> dict:
    integration = payload.integration
    values = _effective_settings_values(
        payload.values.model_dump(exclude_unset=True) if payload.values else None
    )

    try:
        if integration == "google":
            client_id = values.get("google_client_id", "")
            client_secret = values.get("google_client_secret", "")
            if not client_id or not client_secret:
                return {"ok": False, "integration": integration, "message": "Client ID and Secret required"}
            # Validate format
            if not client_id.endswith(".apps.googleusercontent.com"):
                return {"ok": False, "integration": integration, "message": "Invalid Client ID format"}
            if not client_secret.startswith("GOCSPX-"):
                return {"ok": False, "integration": integration, "message": "Invalid Client Secret format"}
            return {
                "ok": True,
                "integration": integration,
                "message": "Google OAuth credentials valid. Save to enable Sign in with Google.",
            }

        if integration == "tmdb":
            if not values["tmdb_api_key"]:
                return {"ok": False, "integration": integration, "message": "TMDB_API_KEY missing"}
            rows = await TMDBClient(
                api_key=values["tmdb_api_key"],
                timeout_seconds=settings.source_timeout_seconds,
            ).upcoming_movies(page=1)
            return {
                "ok": True,
                "integration": integration,
                "message": f"TMDB reachable ({len(rows)} upcoming rows)",
            }

        if integration == "rottentomatoes":
            if not values["rottentomatoes_list_url"]:
                return {
                    "ok": False,
                    "integration": integration,
                    "message": "ROTTENTOMATOES_LIST_URL missing",
                }
            rows = await RottenTomatoesClient(settings.source_timeout_seconds).browse_movies(
                values["rottentomatoes_list_url"]
            )
            return {
                "ok": True,
                "integration": integration,
                "message": f"Rotten Tomatoes reachable ({len(rows)} parsed rows)",
            }

        if integration == "releases":
            if not values["releases_url"]:
                return {"ok": False, "integration": integration, "message": "RELEASES_URL missing"}
            rows = await ReleasesClient(settings.source_timeout_seconds).upcoming_movies(
                values["releases_url"]
            )
            return {
                "ok": True,
                "integration": integration,
                "message": f"Releases.com reachable ({len(rows)} parsed rows)",
            }

        if integration == "rogerebert":
            if not values["rogerebert_reviews_url"]:
                return {
                    "ok": False,
                    "integration": integration,
                    "message": "ROGEREBERT_REVIEWS_URL missing",
                }
            rows = await RogerEbertClient(settings.source_timeout_seconds).recent_reviews(
                values["rogerebert_reviews_url"],
                limit=20,
            )
            recent_rows = [row for row in rows if row.get("year") in {2025, 2026}]
            return {
                "ok": True,
                "integration": integration,
                "message": (
                    f"RogerEbert reachable ({len(recent_rows)} rows for years 2025/2026, "
                    f"{len(rows)} total parsed)"
                ),
            }

        if integration == "plex":
            if not values["plex_token"]:
                return {"ok": False, "integration": integration, "message": "PLEX_TOKEN missing"}
            rows = await PlexClient(
                base_url=values["plex_base_url"],
                token=values["plex_token"],
                timeout_seconds=settings.source_timeout_seconds,
            ).library_movies()
            return {
                "ok": True,
                "integration": integration,
                "message": f"Plex reachable ({len(rows)} movies)",
            }

        if integration == "radarr":
            if not values["radarr_api_key"]:
                return {"ok": False, "integration": integration, "message": "RADARR_API_KEY missing"}
            rows = await RadarrClient(
                base_url=values["radarr_base_url"],
                api_key=values["radarr_api_key"],
                timeout_seconds=settings.source_timeout_seconds,
            ).movies()
            return {
                "ok": True,
                "integration": integration,
                "message": f"Download service reachable ({len(rows)} tracked movies)",
            }

        if integration == "nzbgeek":
            if not values["nzbgeek_rss_url"]:
                return {"ok": False, "integration": integration, "message": "NZBGEEK_RSS_URL missing"}
            if (
                ("{API_KEY}" in values["nzbgeek_rss_url"] or "${API_KEY}" in values["nzbgeek_rss_url"])
                and not values["nzbgeek_api_key"]
            ):
                return {"ok": False, "integration": integration, "message": "NZBGEEK_API_KEY missing"}
            rows = await UsenetClient(
                base_url="https://api.nzbgeek.info",
                api_key=values["nzbgeek_api_key"] or "",
                timeout_seconds=settings.source_timeout_seconds,
            ).movie_rss_feed(
                rss_url=values["nzbgeek_rss_url"],
                api_key=values["nzbgeek_api_key"],
            )
            return {
                "ok": True,
                "integration": integration,
                "message": f"NZBGeek RSS reachable ({len(rows)} items)",
            }

        if integration == "drunkenslug":
            if not values["drunkenslug_api_key"]:
                return {"ok": False, "integration": integration, "message": "DRUNKENSLUG_API_KEY missing"}
            rows = await UsenetClient(
                base_url=values["drunkenslug_base_url"],
                api_key=values["drunkenslug_api_key"],
                timeout_seconds=settings.source_timeout_seconds,
            ).movie_search(query="test")
            return {
                "ok": True,
                "integration": integration,
                "message": f"DrunkenSlug reachable ({len(rows)} rows)",
            }

        if integration == "usenet":
            if not values["usenet_api_key"]:
                return {"ok": False, "integration": integration, "message": "USENET_API_KEY missing"}
            rows = await UsenetClient(
                base_url=values["usenet_base_url"],
                api_key=values["usenet_api_key"],
                timeout_seconds=settings.source_timeout_seconds,
            ).movie_search(query="")
            return {
                "ok": True,
                "integration": integration,
                "message": f"Usenet indexer reachable ({len(rows)} rows)",
            }

        if integration == "ollama":
            if not values["ollama_base_url"]:
                return {"ok": False, "integration": integration, "message": "OLLAMA_BASE_URL missing"}

            client = OllamaClient(
                base_url=values["ollama_base_url"],
                model=values["ollama_model"],
                timeout_seconds=settings.source_timeout_seconds,
            )
            health = await client.health_check()
            if not health.get("ok"):
                return {
                    "ok": False,
                    "integration": integration,
                    "message": health.get("error", "Unable to connect to Ollama"),
                }

            model_status = "available" if health["model_available"] else "not found"
            if not health["model_available"]:
                return {
                    "ok": False,
                    "integration": integration,
                    "message": (
                        f"Ollama reachable ({health['models_count']} models) "
                        f"but model '{values['ollama_model']}' was not found"
                    ),
                }
            return {
                "ok": True,
                "integration": integration,
                "message": f"Ollama reachable ({health['models_count']} models, {values['ollama_model']} {model_status})",
            }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "integration": integration, "message": str(exc)}

    return {"ok": False, "integration": integration, "message": "Unsupported integration"}


# ===== Explanation Endpoint =====


class ExplanationRequest(BaseModel):
    title: str
    year: int | None = None
    score: float = 0.0
    reasons: list[dict] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    overview: str | None = None


@app.post("/api/explain")
async def explain_recommendation(payload: ExplanationRequest) -> dict:
    """Generate a natural language explanation for a movie recommendation."""
    try:
        explainer = get_explainer()
        explanation = await explainer.explain_recommendation(
            movie_title=payload.title,
            movie_year=payload.year,
            score=payload.score,
            reasons=payload.reasons,
            genres=payload.genres,
            overview=payload.overview,
        )
        return {"ok": True, "explanation": explanation}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "explanation": None, "error": str(exc)}


# ===== Admin Endpoints =====


@app.get("/api/admin/sync-jobs")
async def list_sync_jobs(user: AdminUser, limit: int = Query(default=20, ge=1, le=100)) -> dict:
    """List recent sync jobs (admin only)."""
    jobs = memory_store.recent_sync_jobs(limit=limit)
    return {"ok": True, "jobs": jobs}


@app.post("/api/admin/sync/{job_type}")
async def trigger_sync(user: AdminUser, job_type: str) -> dict:
    """Trigger a manual catalog sync (admin only)."""
    if job_type not in ("oscars", "criterion", "usenet_poll"):
        return {"ok": False, "message": f"Unknown job type: {job_type}"}

    try:
        from app.jobs import enqueue_sync_job, is_redis_available

        if is_redis_available():
            job_id = enqueue_sync_job(job_type)
            if job_id:
                return {"ok": True, "message": f"Sync job queued: {job_id}", "job_id": job_id}

        # Fallback: run synchronously
        if job_type == "usenet_poll":
            from app.jobs.tasks.usenet_poll import poll_usenet_releases

            result = poll_usenet_releases()
        else:
            from app.jobs.tasks.catalog_sync import sync_catalog

            result = sync_catalog(job_type)
        return {"ok": True, "message": "Sync completed", "result": result}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc)}


@app.get("/api/admin/users")
async def list_users(user: AdminUser, limit: int = Query(default=100, ge=1, le=500)) -> dict:
    """List all users (admin only)."""
    users = memory_store.list_users(limit=limit)
    return {"ok": True, "users": users}


@app.get("/api/admin/catalog-status")
async def get_catalog_status(user: AuthenticatedUser) -> dict:
    """Get catalog sync status (last sync times)."""
    oscars_job = memory_store.last_sync_job("oscars")
    criterion_job = memory_store.last_sync_job("criterion")

    return {
        "ok": True,
        "oscars": {
            "last_sync": oscars_job["completed_at"] if oscars_job else None,
            "items": oscars_job["items_processed"] if oscars_job else 0,
        },
        "criterion": {
            "last_sync": criterion_job["completed_at"] if criterion_job else None,
            "items": criterion_job["items_processed"] if criterion_job else 0,
        },
    }
