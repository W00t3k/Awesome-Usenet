from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from app.agents.base import MovieAgent
from app.models import AgentContext, MovieCandidate, SourcePayload

if TYPE_CHECKING:
    from app.services.memory_store import MemoryStore


class DisneyAgent(MovieAgent):
    """Agent that provides Disney Animation Studios classics."""

    name = "disney"

    def __init__(self, dataset_path: Path, memory_store: "MemoryStore | None" = None):
        self._dataset_path = dataset_path
        self._memory_store = memory_store

    async def collect(self, context: AgentContext) -> SourcePayload:
        rows = self._load_data()
        if not rows:
            return SourcePayload(metadata={"notes": "Disney dataset missing"})

        movies: list[MovieCandidate] = []
        for row in rows:
            title = row.get("title")
            year = row.get("year")
            era = row.get("era", "")
            if not title:
                continue
            evidence = ["Disney Animation Studios"]
            if era:
                evidence.append(era)
            movies.append(
                MovieCandidate(
                    movie_id=f"disney:{title.lower().replace(' ', '_')}",
                    title=title,
                    year=year,
                    source_tags=["disney", "animation", "family"],
                    evidence=evidence,
                )
            )

        return SourcePayload(
            movies=movies,
            metadata={"notes": f"Loaded {len(movies)} Disney films"},
        )

    def _load_data(self) -> list[dict]:
        if self._memory_store:
            try:
                cached_data, _ = self._memory_store.get_catalog_cache("disney")
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
