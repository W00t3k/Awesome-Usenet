from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from app.agents.base import MovieAgent
from app.models import AgentContext, MovieCandidate, SourcePayload

if TYPE_CHECKING:
    from app.services.memory_store import MemoryStore


class OscarAgent(MovieAgent):
    name = "oscars"

    def __init__(self, dataset_path: Path, memory_store: "MemoryStore | None" = None):
        self._dataset_path = dataset_path
        self._memory_store = memory_store

    async def collect(self, context: AgentContext) -> SourcePayload:
        rows = self._load_data()
        if not rows:
            return SourcePayload(metadata={"notes": "Oscars dataset missing"})

        movies: list[MovieCandidate] = []
        for row in rows:
            year = row.get("year")
            winner = row.get("winner")
            if winner:
                movies.append(
                    MovieCandidate(
                        movie_id=f"oscars:{winner.lower().replace(' ', '_')}",
                        title=winner,
                        year=year,
                        source_tags=["oscars", "best-picture-winner"],
                        evidence=[f"Best Picture winner ({year})"],
                    )
                )
            for nominee in row.get("nominees", []):
                movies.append(
                    MovieCandidate(
                        movie_id=f"oscars:{nominee.lower().replace(' ', '_')}",
                        title=nominee,
                        year=year,
                        source_tags=["oscars", "best-picture-nominee"],
                        evidence=[f"Best Picture nominee ({year})"],
                    )
                )

        return SourcePayload(
            movies=movies,
            metadata={"notes": f"Loaded {len(rows)} Oscar years"},
        )

    def _load_data(self) -> list[dict]:
        """Load Oscar data from cache first, then fallback to JSON file."""
        # Try catalog cache first
        if self._memory_store:
            try:
                cached_data, synced_at = self._memory_store.get_catalog_cache("oscars")
                if cached_data:
                    return cached_data
            except Exception:
                pass

        # Fallback to JSON file
        if self._dataset_path.exists():
            try:
                return json.loads(self._dataset_path.read_text())
            except Exception:
                pass

        return []
