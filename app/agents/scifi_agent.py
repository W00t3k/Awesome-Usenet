from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from app.agents.base import MovieAgent
from app.models import AgentContext, MovieCandidate, SourcePayload

if TYPE_CHECKING:
    from app.services.memory_store import MemoryStore


class SciFiAgent(MovieAgent):
    """Agent that provides essential sci-fi films."""

    name = "scifi"

    def __init__(self, dataset_path: Path, memory_store: "MemoryStore | None" = None):
        self._dataset_path = dataset_path
        self._memory_store = memory_store

    async def collect(self, context: AgentContext) -> SourcePayload:
        rows = self._load_data()
        if not rows:
            return SourcePayload(metadata={"notes": "Sci-Fi dataset missing"})

        movies: list[MovieCandidate] = []
        for row in rows:
            title = row.get("title")
            year = row.get("year")
            if not title:
                continue
            movies.append(
                MovieCandidate(
                    movie_id=f"scifi:{title.lower().replace(' ', '_')}",
                    title=title,
                    year=year,
                    source_tags=["scifi", "science_fiction", "essential"],
                    evidence=["Essential Sci-Fi Film"],
                )
            )

        return SourcePayload(
            movies=movies,
            metadata={"notes": f"Loaded {len(movies)} sci-fi essentials"},
        )

    def _load_data(self) -> list[dict]:
        if self._memory_store:
            try:
                cached_data, _ = self._memory_store.get_catalog_cache("scifi")
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
