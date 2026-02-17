from __future__ import annotations

import asyncio
import contextlib
import html as html_lib
import json
import logging
import random
import re
from datetime import UTC, date, datetime

logger = logging.getLogger(__name__)
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urljoin

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
# New swarm agents
from app.agents.imdb_top250_agent import IMDbTop250Agent
from app.agents.a24_agent import A24Agent
from app.agents.afi_agent import AFI100Agent
from app.agents.cannes_agent import CannesAgent
from app.agents.ghibli_agent import GhibliAgent
from app.agents.sundance_agent import SundanceAgent
from app.agents.bafta_agent import BAFTAAgent
from app.agents.golden_globes_agent import GoldenGlobesAgent
from app.agents.blumhouse_agent import BlumhouseAgent
from app.agents.marvel_dc_agent import MarvelDCAgent
from app.agents.letterboxd_agent import LetterboxdAgent
from app.agents.mubi_agent import MUBIAgent
from app.agents.film_registry_agent import NationalFilmRegistryAgent
from app.agents.metacritic_agent import MetacriticAgent
from app.agents.boxoffice_agent import BoxOfficeAgent
from app.agents.hidden_gems_agent import HiddenGemsAgent
from app.agents.directors_agent import DirectorsAgent
from app.agents.decades_agent import DecadesAgent
from app.agents.sight_sound_agent import SightSoundAgent
from app.agents.pixar_agent import PixarAgent
from app.agents.disney_agent import DisneyAgent
from app.agents.horror_classics_agent import HorrorClassicsAgent
from app.agents.scifi_agent import SciFiAgent
from app.agents.anime_agent import AnimeAgent
from app.agents.korean_cinema_agent import KoreanCinemaAgent
from app.agents.film_noir_agent import FilmNoirAgent
from app.agents.neon_agent import NeonAgent
from app.clients.http_client import HTTPClient
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
from app.services.plex_channel_schedule import PlexChannelScheduleService
from app.services.plex_station import PlexStationService
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
        # New swarm agents
        IMDbTop250Agent(
            dataset_path=project_root / "data/imdb_top250.json",
            memory_store=memory_store,
        ),
        A24Agent(
            dataset_path=project_root / "data/a24_films.json",
            memory_store=memory_store,
        ),
        AFI100Agent(
            dataset_path=project_root / "data/afi100.json",
            memory_store=memory_store,
        ),
        CannesAgent(
            dataset_path=project_root / "data/cannes_palme_dor.json",
            memory_store=memory_store,
        ),
        GhibliAgent(
            dataset_path=project_root / "data/ghibli_films.json",
            memory_store=memory_store,
        ),
        SundanceAgent(
            dataset_path=project_root / "data/sundance_films.json",
            memory_store=memory_store,
        ),
        BAFTAAgent(
            dataset_path=project_root / "data/bafta_winners.json",
            memory_store=memory_store,
        ),
        GoldenGlobesAgent(
            dataset_path=project_root / "data/golden_globes.json",
            memory_store=memory_store,
        ),
        BlumhouseAgent(
            dataset_path=project_root / "data/blumhouse_films.json",
            memory_store=memory_store,
        ),
        MarvelDCAgent(
            dataset_path=project_root / "data/marvel_dc.json",
            memory_store=memory_store,
        ),
        LetterboxdAgent(
            dataset_path=project_root / "data/letterboxd_top.json",
            memory_store=memory_store,
        ),
        MUBIAgent(
            dataset_path=project_root / "data/mubi_curated.json",
            memory_store=memory_store,
        ),
        NationalFilmRegistryAgent(
            dataset_path=project_root / "data/film_registry.json",
            memory_store=memory_store,
        ),
        MetacriticAgent(
            dataset_path=project_root / "data/metacritic_90.json",
            memory_store=memory_store,
        ),
        BoxOfficeAgent(
            dataset_path=project_root / "data/boxoffice_hits.json",
            memory_store=memory_store,
        ),
        HiddenGemsAgent(
            dataset_path=project_root / "data/hidden_gems.json",
            memory_store=memory_store,
        ),
        DirectorsAgent(
            dataset_path=project_root / "data/directors_spotlight.json",
            memory_store=memory_store,
        ),
        DecadesAgent(
            dataset_path=project_root / "data/decades_essentials.json",
            memory_store=memory_store,
        ),
        SightSoundAgent(
            dataset_path=project_root / "data/sight_sound_top100.json",
            memory_store=memory_store,
        ),
        PixarAgent(
            dataset_path=project_root / "data/pixar_films.json",
            memory_store=memory_store,
        ),
        DisneyAgent(
            dataset_path=project_root / "data/disney_classics.json",
            memory_store=memory_store,
        ),
        HorrorClassicsAgent(
            dataset_path=project_root / "data/horror_classics.json",
            memory_store=memory_store,
        ),
        SciFiAgent(
            dataset_path=project_root / "data/scifi_essentials.json",
            memory_store=memory_store,
        ),
        AnimeAgent(
            dataset_path=project_root / "data/anime_essentials.json",
            memory_store=memory_store,
        ),
        KoreanCinemaAgent(
            dataset_path=project_root / "data/korean_cinema.json",
            memory_store=memory_store,
        ),
        FilmNoirAgent(
            dataset_path=project_root / "data/film_noir.json",
            memory_store=memory_store,
        ),
        NeonAgent(
            dataset_path=project_root / "data/neon_films.json",
            memory_store=memory_store,
        ),
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
plex_station_service = PlexStationService()
plex_channel_schedule = PlexChannelScheduleService(project_root / settings.data_dir / "plex_channel_schedule.json")
plex_channel_scheduler_stop = asyncio.Event()
plex_channel_scheduler_task: asyncio.Task | None = None
_plex_machine_identifier_cache: str | None = None

# Initialize auth module with memory store
set_memory_store(memory_store)


async def _reload_runtime() -> None:
    global memory_store, swarm
    async with runtime_lock:
        memory_store, swarm = _build_runtime()


async def _run_plex_channel_scheduler_loop() -> None:
    await asyncio.sleep(3)
    while not plex_channel_scheduler_stop.is_set():
        try:
            slot = plex_channel_schedule.due_slot()
            if slot:
                try:
                    await _refresh_plex_tv_channel(reason="schedule", scheduled_slot=slot)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Scheduled Plex TV refresh failed (%s): %s", slot, exc)
            elif plex_channel_schedule.due_interval():
                try:
                    await _refresh_plex_tv_channel(reason="interval")
                except Exception as exc:  # noqa: BLE001
                    logger.error("Interval Plex TV refresh failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("Plex TV scheduler loop error: %s", exc)
        try:
            await asyncio.wait_for(plex_channel_scheduler_stop.wait(), timeout=30)
        except TimeoutError:
            continue


@app.on_event("startup")
async def _on_startup() -> None:
    global plex_channel_scheduler_task
    plex_channel_scheduler_stop.clear()
    if plex_channel_scheduler_task is None or plex_channel_scheduler_task.done():
        plex_channel_scheduler_task = asyncio.create_task(_run_plex_channel_scheduler_loop())


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    global plex_channel_scheduler_task
    plex_channel_scheduler_stop.set()
    task = plex_channel_scheduler_task
    if task is None:
        return
    with contextlib.suppress(asyncio.CancelledError):
        await task
    plex_channel_scheduler_task = None


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

        tmdb_id = movie.get("tmdbId")
        try:
            tmdb_id = int(tmdb_id) if tmdb_id is not None else None
        except (TypeError, ValueError):
            tmdb_id = None

        items.append(
            {
                "queue_id": queue_id,
                "movie_id": movie_id,
                "tmdb_id": tmdb_id,
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


@app.get("/tv", response_class=HTMLResponse)
async def tv_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="tv.html",
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
    count: int = Query(default=24, ge=1, le=500),
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
        count=min(count * 4, 600),
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
    """Fetch new movie releases from NZBGeek GeekSeek new_movies page."""

    def parse_geekseek_payload(raw: str, max_items: int) -> list[dict]:
        text = (raw or "").strip()
        if not text:
            return []

        # Some NZBGeek routes can respond with RSS/XML depending on session/auth state.
        lowered = text.lower()
        if "<rss" in lowered and "<item" in lowered:
            try:
                return UsenetClient._parse_rss_items(text)[:max_items]
            except Exception:
                pass

        rows: list[dict] = []
        seen_links: set[str] = set()
        seen_titles: set[str] = set()

        def add_row(
            *,
            title: str,
            link: str | None,
            pub_date: str | None = None,
            description: str | None = None,
            cover_url: str | None = None,
            imdb_id: str | None = None,
        ) -> None:
            cleaned_title = re.sub(r"\s+", " ", (title or "")).strip()
            if not cleaned_title:
                return
            title_key = cleaned_title.casefold()
            link_key = (link or "").strip()
            if title_key in seen_titles:
                return
            if link_key and link_key in seen_links:
                return
            seen_titles.add(title_key)
            if link_key:
                seen_links.add(link_key)
            rows.append(
                {
                    "title": cleaned_title,
                    "link": link_key or None,
                    "pub_date": (pub_date or "").strip() or None,
                    "description": (description or "").strip() or None,
                    "cover_url": (cover_url or "").strip() or None,
                    "imdb_id": (imdb_id or "").strip() or None,
                }
            )

        date_re = re.compile(
            r"\b(?:\d{4}-\d{2}-\d{2}|[A-Z][a-z]{2,9}\s+\d{1,2},\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})\b"
        )
        imdb_re = re.compile(r"(tt\d{6,10})")

        def parse_with_regex() -> None:
            anchor_re = re.compile(
                r"<a[^>]*href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<body>.*?)</a>",
                re.IGNORECASE | re.DOTALL,
            )
            title_attr_re = re.compile(r"title=[\"'](?P<title>[^\"']+)[\"']", re.IGNORECASE)
            tag_re = re.compile(r"<[^>]+>")
            img_re = re.compile(
                r"<img[^>]*(?:data-src|src)=[\"'](?P<src>[^\"']+)[\"'][^>]*>",
                re.IGNORECASE | re.DOTALL,
            )

            for match in anchor_re.finditer(text):
                href = str(match.group("href") or "").strip()
                href_lower = href.lower()
                if "/details/" not in href_lower and "t=get" not in href_lower:
                    continue

                full_anchor = match.group(0) or ""
                title_match = title_attr_re.search(full_anchor)
                raw_title = str(title_match.group("title") if title_match else "").strip()
                if not raw_title:
                    body_text = tag_re.sub(" ", match.group("body") or "")
                    raw_title = re.sub(r"\s+", " ", html_lib.unescape(body_text)).strip()

                if not raw_title:
                    continue
                if raw_title.casefold() in {"download", "download nzb", "get nzb"}:
                    continue

                start = max(0, match.start() - 800)
                end = min(len(text), match.end() + 800)
                context = text[start:end]
                context_plain = re.sub(r"\s+", " ", html_lib.unescape(tag_re.sub(" ", context))).strip()

                pub_date_match = date_re.search(context_plain)
                pub_date = pub_date_match.group(0) if pub_date_match else None

                imdb_match = imdb_re.search(context)
                imdb_id = imdb_match.group(1) if imdb_match else None

                image_match = img_re.search(context)
                cover_url = image_match.group("src").strip() if image_match else None
                if cover_url:
                    cover_url = urljoin("https://nzbgeek.info", cover_url)

                add_row(
                    title=html_lib.unescape(raw_title),
                    link=urljoin("https://nzbgeek.info", href),
                    pub_date=pub_date,
                    description=context_plain,
                    cover_url=cover_url,
                    imdb_id=imdb_id,
                )
                if len(rows) >= max_items:
                    break

        try:
            from bs4 import BeautifulSoup
        except Exception:
            parse_with_regex()
            return rows[:max_items]

        soup = BeautifulSoup(text, "html.parser")

        for anchor in soup.select("a[href]"):
            href = str(anchor.get("href") or "").strip()
            href_lower = href.lower()
            if not href:
                continue
            if "/details/" not in href_lower and "t=get" not in href_lower:
                continue

            container = anchor.find_parent(["article", "li", "tr", "div"]) or anchor
            raw_title = (
                str(anchor.get("title") or "").strip()
                or str(container.get("data-title") or "").strip()
                or anchor.get_text(" ", strip=True)
            )
            if not raw_title:
                continue
            if raw_title.casefold() in {"download", "download nzb", "get nzb"}:
                continue

            context_text = container.get_text(" ", strip=True)
            pub_date_match = date_re.search(context_text or "")
            pub_date = pub_date_match.group(0) if pub_date_match else None

            img = container.find("img")
            cover_url = None
            if img is not None:
                cover_url = str(img.get("data-src") or img.get("src") or "").strip() or None
                if cover_url:
                    cover_url = urljoin("https://nzbgeek.info", cover_url)

            imdb_id = None
            imdb_link = container.find("a", href=re.compile(r"imdb\.com/title/tt\d{6,10}", re.IGNORECASE))
            if imdb_link:
                match = imdb_re.search(str(imdb_link.get("href") or ""))
                if match:
                    imdb_id = match.group(1)

            full_link = urljoin("https://nzbgeek.info", href)
            add_row(
                title=raw_title,
                link=full_link,
                pub_date=pub_date,
                description=context_text,
                cover_url=cover_url,
                imdb_id=imdb_id,
            )

            if len(rows) >= max_items:
                break

        # Some page variants expose preloaded JSON blobs with richer fields.
        if len(rows) < max_items:
            for script in soup.select("script[type='application/ld+json'], script"):
                script_text = (script.string or script.get_text() or "").strip()
                if not script_text or "new_movies" not in script_text and "itemListElement" not in script_text:
                    continue
                try:
                    payload = json.loads(script_text)
                except Exception:
                    continue

                objects = payload if isinstance(payload, list) else [payload]
                for obj in objects:
                    if not isinstance(obj, dict):
                        continue
                    items = obj.get("itemListElement")
                    if not isinstance(items, list):
                        continue
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        target = item.get("item") if isinstance(item.get("item"), dict) else item
                        title = str(target.get("name") or target.get("title") or "").strip()
                        if not title:
                            continue
                        add_row(
                            title=title,
                            link=target.get("url"),
                            pub_date=target.get("datePublished") or target.get("dateCreated"),
                            description=target.get("description"),
                            cover_url=target.get("image"),
                            imdb_id=None,
                        )
                        if len(rows) >= max_items:
                            break
                    if len(rows) >= max_items:
                        break
                if len(rows) >= max_items:
                    break

        if not rows:
            parse_with_regex()

        return rows[:max_items]

    # Get API key from settings
    api_key = settings.nzbgeek_api_key or ""
    if not api_key and settings.nzbgeek_rss_url:
        match = re.search(r'(?:apikey|r)=([^&]+)', settings.nzbgeek_rss_url)
        if match:
            api_key = match.group(1)

    if not api_key:
        return []

    try:
        http = HTTPClient(timeout_seconds=settings.source_timeout_seconds)
        geekseek_url = "https://nzbgeek.info/geekseek.php"
        raw_payload = await http.get_text(
            geekseek_url,
            params={
                "new_movies": "",
                "r": api_key,
                "apikey": api_key,
            },
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        rows = parse_geekseek_payload(raw_payload, max_items=limit * 3)
        if rows:
            def parse_date(item: dict) -> float:
                pd = item.get("pub_date") or ""
                try:
                    dt = parsedate_to_datetime(str(pd))
                    return dt.timestamp()
                except Exception:
                    return 0.0

            rows.sort(key=parse_date, reverse=True)
            return rows[:limit]

        logger.warning("NZBGeek geekseek new_movies returned no parsable rows; falling back to RSS.")
        client = UsenetClient(
            base_url="https://api.nzbgeek.info",
            api_key=api_key,
            timeout_seconds=settings.source_timeout_seconds,
        )
        movies_url = f"https://api.nzbgeek.info/rss?t=new_movies&limit={limit}&r={api_key}"
        return await client.movie_rss_feed(rss_url=movies_url, api_key=api_key)

    except Exception as exc:
        logger.warning(f"Failed to fetch NZBGeek GeekSeek new_movies: {exc}")
        return []


@app.get("/api/usenet/latest")
async def get_usenet_latest(
    limit: int = Query(default=12, ge=1, le=50),
) -> dict:
    """Get latest new movie releases from NZBGeek GeekSeek new_movies."""
    checked_at = datetime.now(UTC).isoformat()
    last_poll_row = memory_store.last_sync_job("usenet_poll")
    last_poll_at = (
        (last_poll_row.get("completed_at") or last_poll_row.get("started_at"))
        if last_poll_row
        else None
    )
    try:
        # Fetch from NZBGeek GeekSeek new_movies page/feed
        raw_movies = await _fetch_nzbgeek_movies(limit=limit * 3)
        feed_source = "nzbgeek_geekseek_new_movies"

        if not raw_movies:
            # Fallback to crawl if direct fetch fails
            data = await _crawl_usenet_releases(limit=limit * 2, query=None)
            raw_movies = data.get("items", [])
            feed_source = "crawl_fallback"

        # Create poster client for enrichment
        _poster_client = None
        if settings.tmdb_api_key:
            _poster_client = PosterLookupClient(
                timeout_seconds=settings.source_timeout_seconds,
                tmdb_api_key=settings.tmdb_api_key,
            )

        # Enrich with posters - use NZBGeek cover first, then TMDB fallback
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

            # Use cover from NZBGeek if available
            poster_url = r.get("cover_url") or None
            overview = ""
            imdb_id = r.get("imdb_id") or None

            # Fallback to TMDB if no cover from NZBGeek
            if not poster_url and _poster_client and title:
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
                "imdb_id": imdb_id,
                "link": r.get("link"),
            })

            if len(enriched) >= limit:
                break

        return {
            "ok": True,
            "releases": enriched,
            "count": len(enriched),
            "checked_at": checked_at,
            "last_poll_at": last_poll_at,
            "poll_interval_minutes": settings.usenet_poll_interval_minutes,
            "feed_source": feed_source,
        }
    except Exception as exc:
        logger.warning(f"Failed to get latest usenet: {exc}")
        return {
            "ok": False,
            "releases": [],
            "error": str(exc),
            "checked_at": checked_at,
            "last_poll_at": last_poll_at,
            "poll_interval_minutes": settings.usenet_poll_interval_minutes,
        }


@app.get("/api/usenet/check")
async def check_usenet_availability(
    title: str = Query(...),
    year: int | None = Query(default=None),
) -> dict:
    """Check if a movie is available on NZBGeek/Usenet."""
    api_key = settings.nzbgeek_api_key or ""
    if not api_key and settings.nzbgeek_rss_url:
        match = re.search(r'(?:apikey|r)=([^&]+)', settings.nzbgeek_rss_url)
        if match:
            api_key = match.group(1)

    if not api_key:
        return {"ok": False, "available": False, "message": "NZBGeek API key not configured"}

    try:
        import httpx

        # Search NZBGeek for this movie
        search_query = title
        if year:
            search_query = f"{title} {year}"

        search_url = f"https://api.nzbgeek.info/api?t=search&cat=2000&q={quote(search_query)}&apikey={api_key}&o=json"

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(search_url)
            if resp.status_code != 200:
                return {"ok": False, "available": False, "message": f"NZBGeek returned {resp.status_code}"}

            data = resp.json()
            items = data.get("channel", {}).get("item", [])

            # Check if any results match
            if items:
                # Return available with details
                best_match = items[0] if isinstance(items, list) else items
                return {
                    "ok": True,
                    "available": True,
                    "result_count": len(items) if isinstance(items, list) else 1,
                    "title": title,
                    "year": year,
                    "checked_at": datetime.now(UTC).isoformat(),
                }
            else:
                return {
                    "ok": True,
                    "available": False,
                    "result_count": 0,
                    "title": title,
                    "year": year,
                    "checked_at": datetime.now(UTC).isoformat(),
                }

    except Exception as exc:
        logger.warning(f"Error checking NZBGeek availability: {exc}")
        return {"ok": False, "available": False, "message": str(exc)}


@app.delete("/api/radarr/movie/{movie_id}")
async def delete_radarr_movie(
    movie_id: int,
    delete_files: bool = Query(default=True),
) -> dict:
    """Delete a movie from Radarr."""
    if not settings.radarr_base_url or not settings.radarr_api_key:
        return {"ok": False, "message": "Radarr not configured"}

    try:
        import httpx

        url = f"{settings.radarr_base_url.rstrip('/')}/api/v3/movie/{movie_id}"
        params = {"deleteFiles": str(delete_files).lower(), "addImportExclusion": "false"}
        headers = {"X-Api-Key": settings.radarr_api_key}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(url, params=params, headers=headers)
            if resp.status_code in (200, 204):
                return {"ok": True, "message": f"Movie {movie_id} deleted from Radarr"}
            else:
                return {"ok": False, "message": f"Radarr returned {resp.status_code}"}

    except Exception as exc:
        logger.warning(f"Error deleting from Radarr: {exc}")
        return {"ok": False, "message": str(exc)}


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
                "tmdb_id": m.get("tmdbId"),
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


class PlexWatchlistRequest(BaseModel):
    title: str
    year: int | None = None
    tmdb_id: int | None = None
    imdb_id: str | None = None


@app.post("/api/plex/watchlist")
async def add_to_plex_watchlist(req: PlexWatchlistRequest) -> dict:
    """Add a movie to the Plex Watchlist."""
    if not settings.plex_token:
        return {"ok": False, "message": "PLEX_TOKEN not configured"}

    import httpx

    headers = {
        "X-Plex-Token": settings.plex_token,
        "X-Plex-Client-Identifier": "majic-movie-selector",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Try to find the movie on Plex Discover using TMDB ID
            rating_key = None

            if req.tmdb_id:
                search_url = f"https://discover.provider.plex.tv/library/search?query=tmdb://{req.tmdb_id}&searchTypes=movie&limit=1"
                resp = await client.get(search_url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("MediaContainer", {}).get("Metadata", [])
                    if results:
                        rating_key = results[0].get("ratingKey")

            # Fallback: search by title and year
            if not rating_key:
                query = req.title
                if req.year:
                    query = f"{req.title} {req.year}"
                search_url = f"https://discover.provider.plex.tv/library/search?query={quote(query)}&searchTypes=movie&limit=5"
                resp = await client.get(search_url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("MediaContainer", {}).get("Metadata", [])
                    for result in results:
                        result_title = result.get("title", "").lower()
                        result_year = result.get("year")
                        if result_title == req.title.lower():
                            if not req.year or result_year == req.year:
                                rating_key = result.get("ratingKey")
                                break
                    # If no exact match, use first result
                    if not rating_key and results:
                        rating_key = results[0].get("ratingKey")

            if not rating_key:
                return {"ok": False, "message": f"Could not find '{req.title}' on Plex"}

            # Add to watchlist
            watchlist_url = f"https://discover.provider.plex.tv/actions/addToWatchlist?ratingKey={rating_key}"
            resp = await client.put(watchlist_url, headers=headers)

            if resp.status_code in (200, 201, 204):
                return {"ok": True, "message": f"Added '{req.title}' to Plex Watchlist"}
            else:
                return {"ok": False, "message": f"Failed to add to watchlist: {resp.status_code}"}

    except Exception as e:
        logger.error(f"Error adding to Plex Watchlist: {e}")
        return {"ok": False, "message": str(e)}


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
    enriched_station["up_next"] = [enrich_item(item) for item in (enriched_station.get("up_next") or [])]
    enriched_station["queue"] = [enrich_item(item) for item in (enriched_station.get("queue") or [])]
    return enriched_station


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

    state = plex_channel_schedule.snapshot()
    playlist_name = (override_playlist_name or state.get("playlist_name") or "Majic TV Station").strip()
    if not playlist_name:
        playlist_name = "Majic TV Station"

    count = override_count if override_count is not None else int(state.get("count") or 25)
    count = max(1, min(int(count), 250))

    min_year = override_min_year if override_min_year is not None else state.get("min_year")
    max_year = override_max_year if override_max_year is not None else state.get("max_year")
    if min_year is not None:
        min_year = int(min_year)
    if max_year is not None:
        max_year = int(max_year)
    if min_year is not None and max_year is not None and min_year > max_year:
        min_year, max_year = max_year, min_year

    client = PlexClient(
        base_url=settings.plex_base_url,
        token=settings.plex_token,
        timeout_seconds=settings.source_timeout_seconds,
    )

    try:
        rows = await client.library_movies()
        queue = plex_station_service.build_queue(
            rows,
            count=count,
            seed=override_seed,
            min_year=min_year,
            max_year=max_year,
        )
        rating_keys = [str(item.get("rating_key") or "").strip() for item in queue]
        rating_keys = [key for key in rating_keys if key]
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
                collection = await client.upsert_collection(
                    section_key=section_key,
                    title=playlist_name,
                    rating_keys=rating_keys,
                )
                collection_key = str(collection.get("ratingKey") or "").strip()
                collection_payload = {
                    "title": collection.get("title"),
                    "rating_key": collection_key,
                    "item_count": collection.get("childCount"),
                    "web_url": _plex_collection_web_url(collection_key),
                }
        queue_preview = [
            {
                "title": item.get("title"),
                "year": item.get("year"),
                "rating_key": item.get("rating_key"),
                "poster_url": _plex_thumb_url(item.get("thumb")),
                "web_url": _plex_web_url_for_rating_key(item.get("rating_key")),
            }
            for item in queue[:12]
        ]
        autoplay_enabled = bool(state.get("autoplay_enabled", True))
        autoplay_random_offset = bool(state.get("autoplay_random_offset", True))
        autoplay_client = str(state.get("autoplay_client") or "").strip() or None
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
            # Skip intros/credits by selecting a bounded random offset in longer movies.
            if autoplay_random_offset and duration_ms > (45 * 60 * 1000):
                max_offset_ms = max(0, duration_ms - (20 * 60 * 1000))
                if max_offset_ms > 0:
                    offset_ms = random.randint(0, max_offset_ms)

            if movie_rating_key:
                try:
                    playback = await client.start_playback(
                        rating_key=movie_rating_key,
                        client_identifier=autoplay_client,
                        offset_ms=offset_ms,
                    )
                    target = playback.get("client") or {}
                    target_name = str(target.get("name") or target.get("client_identifier") or "").strip() or None
                    plex_channel_schedule.mark_playback(
                        success=True,
                        message=f"Started '{movie_title}' on '{target_name or 'unknown client'}'.",
                        movie_title=movie_title,
                        client_name=target_name,
                        offset_ms=int(playback.get("offset_ms") or 0),
                    )
                    autoplay_result = {
                        "ok": True,
                        "movie_title": movie_title,
                        "offset_ms": int(playback.get("offset_ms") or 0),
                        "client": target,
                    }
                    run_message = f"{run_message} Started '{movie_title}' on {target_name or 'client'}."
                except Exception as exc:  # noqa: BLE001
                    error_message = str(exc)
                    plex_channel_schedule.mark_playback(
                        success=False,
                        message=error_message,
                        movie_title=movie_title,
                        client_name=autoplay_client,
                        offset_ms=offset_ms,
                    )
                    autoplay_result = {
                        "ok": False,
                        "movie_title": movie_title,
                        "offset_ms": offset_ms,
                        "message": error_message,
                    }
                    run_message = f"{run_message} Playback not started: {error_message}"

        schedule_state = plex_channel_schedule.mark_run(
            success=True,
            message=run_message,
            queue_size=len(rating_keys),
            source=reason,
            slot=scheduled_slot,
        )
        return {
            "ok": True,
            "playlist": {
                "title": playlist_name,
                "rating_key": playlist_key,
                "item_count": len(rating_keys),
                "web_url": playlist_url,
            },
            "collection": collection_payload,
            "queue_preview": queue_preview,
            "autoplay": autoplay_result,
            "schedule": schedule_state,
        }
    except Exception as exc:  # noqa: BLE001
        plex_channel_schedule.mark_run(
            success=False,
            message=str(exc),
            queue_size=0,
            source=reason,
            slot=scheduled_slot,
        )
        raise


@app.post("/api/plex/station/start")
async def start_plex_station(payload: PlexStationStartRequest) -> dict:
    if not settings.plex_token:
        return {"ok": False, "message": "PLEX_TOKEN missing"}

    min_year = payload.min_year
    max_year = payload.max_year
    if min_year is not None and max_year is not None and min_year > max_year:
        min_year, max_year = max_year, min_year

    rows = await PlexClient(
        base_url=settings.plex_base_url,
        token=settings.plex_token,
        timeout_seconds=settings.source_timeout_seconds,
    ).library_movies()

    try:
        station = plex_station_service.create_station(
            rows,
            name=payload.name,
            count=payload.count,
            seed=payload.seed,
            min_year=min_year,
            max_year=max_year,
        )
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}

    return {"ok": True, "station": _enrich_station_payload(station)}


@app.get("/api/plex/station")
async def list_plex_stations() -> dict:
    stations = [_enrich_station_payload(station) for station in plex_station_service.list_stations()]
    return {"ok": True, "stations": stations}


@app.get("/api/plex/station/{station_id}")
async def get_plex_station(station_id: str) -> dict:
    station = plex_station_service.get_station(station_id)
    if not station:
        return {"ok": False, "message": "Station not found"}
    return {"ok": True, "station": _enrich_station_payload(station)}


@app.post("/api/plex/station/{station_id}/next")
async def next_plex_station_movie(station_id: str) -> dict:
    try:
        station = plex_station_service.next_movie(station_id)
    except KeyError:
        return {"ok": False, "message": "Station not found"}
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "station": _enrich_station_payload(station)}


@app.delete("/api/plex/station/{station_id}")
async def delete_plex_station(station_id: str) -> dict:
    removed = plex_station_service.delete_station(station_id)
    return {"ok": True, "removed": removed}


@app.get("/api/plex/channel/status")
async def plex_channel_status() -> dict:
    schedule_state = plex_channel_schedule.snapshot()
    configured = bool(settings.plex_token)

    channel = {
        "configured": configured,
        "mode": "plex_playlist",
        "plays_in": "Plex clients (TV, mobile, web) via Playlists and Movies Collections",
        "schedule": schedule_state,
        "playlist": None,
        "collection": None,
    }
    if not configured:
        return {"ok": True, "channel": channel, "message": "PLEX_TOKEN missing"}

    try:
        client = PlexClient(
            base_url=settings.plex_base_url,
            token=settings.plex_token,
            timeout_seconds=settings.source_timeout_seconds,
        )
        title = str(schedule_state.get("playlist_name") or "Majic TV Station")
        playlist = await client.find_playlist_by_title(title)
        if playlist:
            key = str(playlist.get("ratingKey") or "").strip()
            channel["playlist"] = {
                "title": playlist.get("title"),
                "rating_key": key,
                "item_count": playlist.get("leafCount"),
                "duration_ms": playlist.get("duration"),
                "web_url": _plex_playlist_web_url(key),
            }
        movie_sections = await client.movie_sections()
        if movie_sections:
            section_key = str(movie_sections[0].get("key") or "").strip()
            if section_key:
                collection = await client.find_collection_by_title(section_key=section_key, title=title)
                if collection:
                    collection_key = str(collection.get("ratingKey") or "").strip()
                    channel["collection"] = {
                        "title": collection.get("title"),
                        "rating_key": collection_key,
                        "item_count": collection.get("childCount"),
                        "web_url": _plex_collection_web_url(collection_key),
                    }
    except Exception as exc:  # noqa: BLE001
        channel["playlist_error"] = str(exc)

    return {"ok": True, "channel": channel}


@app.get("/api/plex/clients")
async def plex_clients() -> dict:
    if not settings.plex_token:
        return {"ok": False, "clients": [], "message": "PLEX_TOKEN missing"}
    try:
        client = PlexClient(
            base_url=settings.plex_base_url,
            token=settings.plex_token,
            timeout_seconds=settings.source_timeout_seconds,
        )
        rows = await client.list_clients()
        selected = await client.resolve_playback_client()
        return {"ok": True, "clients": rows, "selected": selected}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "clients": [], "message": str(exc)}


@app.post("/api/plex/channel/refresh")
async def refresh_plex_channel(payload: PlexChannelRefreshRequest | None = None) -> dict:
    req = payload or PlexChannelRefreshRequest()
    try:
        result = await _refresh_plex_tv_channel(
            reason="manual",
            override_playlist_name=req.playlist_name,
            override_count=req.count,
            override_seed=req.seed,
            override_min_year=req.min_year,
            override_max_year=req.max_year,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc), "schedule": plex_channel_schedule.snapshot()}


@app.post("/api/plex/channel/schedule")
async def update_plex_channel_schedule(payload: PlexChannelScheduleRequest) -> dict:
    try:
        schedule_state = plex_channel_schedule.update_config(
            enabled=payload.enabled,
            playlist_name=payload.playlist_name,
            count=payload.count,
            min_year=payload.min_year,
            max_year=payload.max_year,
            schedule_times=payload.schedule_times,
            interval_minutes=payload.interval_minutes,
            autoplay_enabled=payload.autoplay_enabled,
            autoplay_client=payload.autoplay_client,
            autoplay_random_offset=payload.autoplay_random_offset,
        )
    except ValueError as exc:
        return {"ok": False, "message": str(exc), "schedule": plex_channel_schedule.snapshot()}

    refresh_payload = None
    if payload.run_now:
        try:
            refresh_payload = await _refresh_plex_tv_channel(
                reason="schedule-run-now",
                override_playlist_name=payload.playlist_name,
                override_count=payload.count,
                override_min_year=payload.min_year,
                override_max_year=payload.max_year,
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc), "schedule": plex_channel_schedule.snapshot()}

    return {"ok": True, "schedule": schedule_state, "refresh": refresh_payload}


@app.post("/api/plex/channel/schedule/disable")
async def disable_plex_channel_schedule() -> dict:
    current = plex_channel_schedule.snapshot()
    schedule_state = plex_channel_schedule.update_config(
        enabled=False,
        playlist_name=str(current.get("playlist_name") or "Majic TV Station"),
        count=int(current.get("count") or 25),
        min_year=current.get("min_year"),
        max_year=current.get("max_year"),
        schedule_times=list(current.get("schedule_times") or ["20:00"]),
        interval_minutes=int(current.get("interval_minutes") or 0),
        autoplay_enabled=bool(current.get("autoplay_enabled", True)),
        autoplay_client=(str(current.get("autoplay_client") or "").strip() or None),
        autoplay_random_offset=bool(current.get("autoplay_random_offset", True)),
    )
    return {"ok": True, "schedule": schedule_state}


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
