from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from app.agents.base import MovieAgent
from app.models import AgentContext, MovieCandidate, SourcePayload

if TYPE_CHECKING:
    from app.services.memory_store import MemoryStore


class HiddenGemsAgent(MovieAgent):
    """Agent that provides hidden gem films - high ratings but low popularity."""

    name = "hidden_gems"

    def __init__(self, dataset_path: Path, memory_store: "MemoryStore | None" = None):
        self._dataset_path = dataset_path
        self._memory_store = memory_store

    async def collect(self, context: AgentContext) -> SourcePayload:
        rows = self._load_data()
        if not rows:
            return SourcePayload(metadata={"notes": "Hidden Gems dataset missing"})

        movies: list[MovieCandidate] = []
        for row in rows:
            title = row.get("title")
            year = row.get("year")
            rating = row.get("rating", "")
            if not title:
                continue
            evidence = ["Hidden Gem - Underseen Masterpiece"]
            if rating:
                evidence.append(f"Rating: {rating}")
            movies.append(
                MovieCandidate(
                    movie_id=f"hidden_gems:{title.lower().replace(' ', '_')}",
                    title=title,
                    year=year,
                    source_tags=["hidden_gems", "underseen"],
                    evidence=evidence,
                )
            )

        return SourcePayload(
            movies=movies,
            metadata={"notes": f"Loaded {len(movies)} hidden gems"},
        )

    def _load_data(self) -> list[dict]:
        if self._memory_store:
            try:
                cached_data, _ = self._memory_store.get_catalog_cache("hidden_gems")
                if cached_data:
                    return cached_data
            except Exception:
                pass

        if self._dataset_path.exists():
            try:
                return json.loads(self._dataset_path.read_text())
            except Exception:
                pass

        return []
