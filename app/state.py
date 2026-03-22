"""
Shared mutable application state.

Populated by main.py at startup; imported by router modules.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Coroutine, Any

if TYPE_CHECKING:
    from app.services.memory_store import MemoryStore
    from app.services.swarm import SwarmOrchestrator
    from app.services.enrichment_service import EnrichmentService
    from app.clients.poster_lookup_client import PosterLookupClient
    from app.services.plex_channel_schedule import PlexChannelScheduleService
    from app.services.plex_station import PlexStationService

# Populated on startup by main.py
memory_store: "MemoryStore"
swarm: "SwarmOrchestrator"
enrichment_service: "EnrichmentService"
poster_lookup_client: "PosterLookupClient | None" = None
plex_channel_schedule: "PlexChannelScheduleService"
plex_station_service: "PlexStationService"

# Registered by main.py so routers can trigger a runtime reload
# without creating a circular import.
_reload_fn: Callable[[], Coroutine[Any, Any, None]] | None = None


def register_reload(fn: Callable[[], Coroutine[Any, Any, None]]) -> None:
    global _reload_fn
    _reload_fn = fn


async def reload_runtime() -> None:
    if _reload_fn is not None:
        await _reload_fn()


async def get_llm_client(provider: str | None = None):
    """Return a UnifiedLLMClient (Groq → Ollama fallback)."""
    from app.config import settings
    from app.clients.llm_client import UnifiedLLMClient
    try:
        return UnifiedLLMClient(
            groq_api_key=settings.groq_api_key,
            groq_model=settings.groq_model,
            ollama_base_url=settings.ollama_base_url,
            ollama_model=settings.ollama_model,
            prefer_provider=provider,
        )
    except Exception:
        return None
