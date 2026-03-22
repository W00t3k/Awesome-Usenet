"""
Majic Movie Selector – application entry point.

This module is intentionally thin: it builds the runtime, wires shared state,
mounts routers, and owns the lifespan events. All route handlers live in
app/routers/*.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import state as app_state
from app.config import settings
from app.services.embedding import EmbeddingService
from app.services.enrichment_service import EnrichmentService
from app.services.memory_store import MemoryStore
from app.services.plex_channel_schedule import PlexChannelScheduleService
from app.services.plex_station import PlexStationService
from app.services.recommender import Recommender
from app.services.swarm import SwarmOrchestrator
from app.clients.llm_client import UnifiedLLMClient
from app.clients.poster_lookup_client import PosterLookupClient
from app.clients.tmdb_client import TMDBClient

logger = logging.getLogger(__name__)

base_dir = Path(__file__).resolve().parent
project_root = base_dir.parent
env_path = project_root / ".env"

load_dotenv(dotenv_path=env_path)


# ── Runtime construction ───────────────────────────────────────────────────────

def _build_runtime() -> tuple[MemoryStore, SwarmOrchestrator, PosterLookupClient]:
    from app.agents.criterion_agent import CriterionAgent
    from app.agents.drunkenslug_agent import DrunkenSlugAgent
    from app.agents.oscar_agent import OscarAgent
    from app.agents.plex_agent import PlexAgent
    from app.agents.releases_agent import ReleasesAgent
    from app.agents.rottentomatoes_agent import RottenTomatoesAgent
    from app.agents.upcoming_agent import UpcomingAgent
    from app.agents.usenet_agent import UsenetAgent
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

    embedding_service = EmbeddingService()
    memory_store = MemoryStore(
        db_path=project_root / settings.memory_db_path,
        embedding_service=embedding_service,
    )

    agents = [
        OscarAgent(dataset_path=project_root / "data/oscars_best_picture.json", memory_store=memory_store, timeout_seconds=settings.source_timeout_seconds),
        CriterionAgent(dataset_path=project_root / "data/criterion_collection.json", memory_store=memory_store),
        UpcomingAgent(tmdb_api_key=settings.tmdb_api_key, timeout_seconds=settings.source_timeout_seconds, fallback_dataset_path=project_root / "data/upcoming_seed.json"),
        RottenTomatoesAgent(list_url=settings.rottentomatoes_list_url, timeout_seconds=settings.source_timeout_seconds, fallback_dataset_path=project_root / "data/rottentomatoes_seed.json"),
        ReleasesAgent(releases_url=settings.releases_url, timeout_seconds=settings.source_timeout_seconds, fallback_dataset_path=project_root / "data/releases_seed.json"),
        PlexAgent(base_url=settings.plex_base_url, token=settings.plex_token, timeout_seconds=settings.source_timeout_seconds),
        UsenetAgent(rss_url=settings.nzbgeek_rss_url, api_key=settings.nzbgeek_api_key, timeout_seconds=settings.source_timeout_seconds),
        DrunkenSlugAgent(base_url=settings.drunkenslug_base_url, api_key=settings.drunkenslug_api_key, timeout_seconds=settings.source_timeout_seconds),
        IMDbTop250Agent(dataset_path=project_root / "data/imdb_top250.json", memory_store=memory_store),
        A24Agent(dataset_path=project_root / "data/a24_films.json", memory_store=memory_store),
        AFI100Agent(dataset_path=project_root / "data/afi100.json", memory_store=memory_store),
        CannesAgent(dataset_path=project_root / "data/cannes_palme_dor.json", memory_store=memory_store),
        GhibliAgent(dataset_path=project_root / "data/ghibli_films.json", memory_store=memory_store),
        SundanceAgent(dataset_path=project_root / "data/sundance_films.json", memory_store=memory_store),
        BAFTAAgent(dataset_path=project_root / "data/bafta_winners.json", memory_store=memory_store),
        GoldenGlobesAgent(dataset_path=project_root / "data/golden_globes.json", memory_store=memory_store),
        BlumhouseAgent(dataset_path=project_root / "data/blumhouse_films.json", memory_store=memory_store),
        MarvelDCAgent(dataset_path=project_root / "data/marvel_dc.json", memory_store=memory_store),
        LetterboxdAgent(dataset_path=project_root / "data/letterboxd_top.json", memory_store=memory_store),
        MUBIAgent(dataset_path=project_root / "data/mubi_curated.json", memory_store=memory_store),
        NationalFilmRegistryAgent(dataset_path=project_root / "data/film_registry.json", memory_store=memory_store),
        MetacriticAgent(dataset_path=project_root / "data/metacritic_90.json", memory_store=memory_store),
        BoxOfficeAgent(dataset_path=project_root / "data/boxoffice_hits.json", memory_store=memory_store),
        HiddenGemsAgent(dataset_path=project_root / "data/hidden_gems.json", memory_store=memory_store),
        DirectorsAgent(dataset_path=project_root / "data/directors_spotlight.json", memory_store=memory_store),
        DecadesAgent(dataset_path=project_root / "data/decades_essentials.json", memory_store=memory_store),
        SightSoundAgent(dataset_path=project_root / "data/sight_sound_top100.json", memory_store=memory_store),
        PixarAgent(dataset_path=project_root / "data/pixar_films.json", memory_store=memory_store),
        DisneyAgent(dataset_path=project_root / "data/disney_classics.json", memory_store=memory_store),
        HorrorClassicsAgent(dataset_path=project_root / "data/horror_classics.json", memory_store=memory_store),
        SciFiAgent(dataset_path=project_root / "data/scifi_essentials.json", memory_store=memory_store),
        AnimeAgent(dataset_path=project_root / "data/anime_essentials.json", memory_store=memory_store),
        KoreanCinemaAgent(dataset_path=project_root / "data/korean_cinema.json", memory_store=memory_store),
        FilmNoirAgent(dataset_path=project_root / "data/film_noir.json", memory_store=memory_store),
        NeonAgent(dataset_path=project_root / "data/neon_films.json", memory_store=memory_store),
    ]

    recommender = Recommender(memory_store=memory_store)
    poster_lookup_client = PosterLookupClient(
        timeout_seconds=settings.source_timeout_seconds,
        tmdb_api_key=settings.tmdb_api_key,
        memory_store=memory_store,
    )
    tmdb_client = TMDBClient(api_key=settings.tmdb_api_key, timeout_seconds=settings.source_timeout_seconds) if settings.tmdb_api_key else None
    llm_client = UnifiedLLMClient(
        groq_api_key=settings.groq_api_key,
        groq_model=settings.groq_model,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
    )
    if llm_client.available:
        logger.info(f"LLM provider: {llm_client.provider}")
    swarm = SwarmOrchestrator(
        agents=agents,
        recommender=recommender,
        poster_lookup_client=poster_lookup_client,
        tmdb_client=tmdb_client,
        llm_client=llm_client if llm_client.available else None,
        memory_store=memory_store,
    )
    return memory_store, swarm, poster_lookup_client


# ── Initial runtime ────────────────────────────────────────────────────────────

_runtime_lock = asyncio.Lock()

memory_store, swarm, poster_lookup_client = _build_runtime()
enrichment_service = EnrichmentService(memory_store, poster_lookup_client)
plex_station_service = PlexStationService()
plex_channel_schedule = PlexChannelScheduleService(project_root / settings.data_dir / "plex_channel_schedule.json")

# Populate shared state module
app_state.memory_store = memory_store
app_state.swarm = swarm
app_state.poster_lookup_client = poster_lookup_client
app_state.enrichment_service = enrichment_service
app_state.plex_station_service = plex_station_service
app_state.plex_channel_schedule = plex_channel_schedule


async def _reload_runtime() -> None:
    global memory_store, swarm, poster_lookup_client, enrichment_service
    async with _runtime_lock:
        enrichment_service.stop()
        memory_store, swarm, poster_lookup_client = _build_runtime()
        enrichment_service = EnrichmentService(memory_store, poster_lookup_client)
        enrichment_service.start()
        app_state.memory_store = memory_store
        app_state.swarm = swarm
        app_state.poster_lookup_client = poster_lookup_client
        app_state.enrichment_service = enrichment_service


app_state.register_reload(_reload_runtime)


# ── FastAPI app ────────────────────────────────────────────────────────────────

app = FastAPI(title=settings.app_title)
templates = Jinja2Templates(directory=str(base_dir / "templates"))
app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")

# ── Auth ───────────────────────────────────────────────────────────────────────

from app.auth.router import auth_router, set_memory_store  # noqa: E402

set_memory_store(memory_store)
app.include_router(auth_router)

# ── Routers ────────────────────────────────────────────────────────────────────

from app.routers import pages, chat, settings_router, servers, seen  # noqa: E402
from app.routers import usenet, downloads, plex, recommendations, admin, mcp  # noqa: E402

pages.set_templates(templates)

for _router_module in (pages, chat, settings_router, servers, seen, usenet, downloads, plex, recommendations, admin, mcp):
    app.include_router(_router_module.router)


# ── Plex channel scheduler ─────────────────────────────────────────────────────

_plex_scheduler_stop = asyncio.Event()
_plex_scheduler_task: asyncio.Task | None = None


async def _run_plex_channel_scheduler_loop() -> None:
    from app.routers.plex import _refresh_plex_tv_channel
    await asyncio.sleep(3)
    while not _plex_scheduler_stop.is_set():
        try:
            slot = app_state.plex_channel_schedule.due_slot()
            if slot:
                try:
                    await _refresh_plex_tv_channel(reason="schedule", scheduled_slot=slot)
                except Exception as exc:
                    logger.error("Scheduled Plex TV refresh failed (%s): %s", slot, exc)
            elif app_state.plex_channel_schedule.due_interval():
                try:
                    await _refresh_plex_tv_channel(reason="interval")
                except Exception as exc:
                    logger.error("Interval Plex TV refresh failed: %s", exc)
        except Exception as exc:
            logger.error("Plex TV scheduler loop error: %s", exc)
        try:
            await asyncio.wait_for(_plex_scheduler_stop.wait(), timeout=30)
        except TimeoutError:
            continue


# ── Lifespan events ────────────────────────────────────────────────────────────

@app.on_event("startup")
async def _on_startup() -> None:
    global _plex_scheduler_task
    _plex_scheduler_stop.clear()
    if _plex_scheduler_task is None or _plex_scheduler_task.done():
        _plex_scheduler_task = asyncio.create_task(_run_plex_channel_scheduler_loop())
    enrichment_service.start()
    logger.info("Background enrichment service started")


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    global _plex_scheduler_task
    logger.info("Initiating graceful shutdown...")
    enrichment_service.stop()
    _plex_scheduler_stop.set()
    task = _plex_scheduler_task
    if task is not None:
        logger.info("Waiting for scheduler task to complete...")
        with contextlib.suppress(asyncio.CancelledError):
            try:
                await asyncio.wait_for(task, timeout=10.0)
            except TimeoutError:
                logger.warning("Scheduler task did not complete in time, cancelling...")
                task.cancel()
        _plex_scheduler_task = None
    from app.clients.http_client import close_shared_client
    await close_shared_client()
    await asyncio.sleep(0.5)
    logger.info("Shutdown complete")
