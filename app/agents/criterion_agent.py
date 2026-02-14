from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from app.agents.base import MovieAgent
from app.models import AgentContext, MovieCandidate, SourcePayload

if TYPE_CHECKING:
    from app.services.memory_store import MemoryStore


class CriterionAgent(MovieAgent):
    name = "criterion"

    def __init__(self, dataset_path: Path, memory_store: "MemoryStore | None" = None):
        self._dataset_path = dataset_path
        self._memory_store = memory_store

    async def collect(self, context: AgentContext) -> SourcePayload:
        rows = self._load_data()
        if not rows:
            return SourcePayload(metadata={"notes": "Criterion dataset missing"})

        movies: list[MovieCandidate] = []
        for row in rows:
            title = row.get("title")
            if not title:
                continue
            raw_identifier = row.get("spine", title)
            normalized_identifier = str(raw_identifier).replace(" ", "_").lower()
            movies.append(
                MovieCandidate(
                    movie_id=f"criterion:{normalized_identifier}",
                    title=title,
                    year=row.get("year"),
                    genres=row.get("genres", []),
                    overview=row.get("overview"),
                    source_tags=["criterion"],
                    evidence=[f"Criterion spine #{row.get('spine', 'n/a')}"]
                    if row.get("spine")
                    else ["In Criterion Collection"],
                )
            )
        return SourcePayload(
            movies=movies,
            metadata={"notes": f"Loaded {len(movies)} Criterion entries"},
        )

    def _load_data(self) -> list[dict]:
        """Load Criterion data from cache first, then fallback to JSON file."""
        # Try catalog cache first
        if self._memory_store:
            try:
                cached_data, synced_at = self._memory_store.get_catalog_cache("criterion")
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
