from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from app.agents.base import MovieAgent
from app.models import AgentContext, MovieCandidate, SourcePayload

if TYPE_CHECKING:
    from app.services.memory_store import MemoryStore


class HorrorClassicsAgent(MovieAgent):
    """Agent that provides classic horror films."""

    name = "horror_classics"

    def __init__(self, dataset_path: Path, memory_store: "MemoryStore | None" = None):
        self._dataset_path = dataset_path
        self._memory_store = memory_store

    async def collect(self, context: AgentContext) -> SourcePayload:
        rows = self._load_data()
        if not rows:
            return SourcePayload(metadata={"notes": "Horror Classics dataset missing"})

        movies: list[MovieCandidate] = []
        for row in rows:
            title = row.get("title")
            year = row.get("year")
            if not title:
                continue
            movies.append(
                MovieCandidate(
                    movie_id=f"horror_classics:{title.lower().replace(' ', '_')}",
                    title=title,
                    year=year,
                    source_tags=["horror_classics", "horror", "essential"],
                    evidence=["Essential Horror Film"],
                )
            )

        return SourcePayload(
            movies=movies,
            metadata={"notes": f"Loaded {len(movies)} horror classics"},
        )

    def _load_data(self) -> list[dict]:
        if self._memory_store:
            try:
                cached_data, _ = self._memory_store.get_catalog_cache("horror_classics")
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
