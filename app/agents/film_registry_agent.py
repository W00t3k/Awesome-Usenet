from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from app.agents.base import MovieAgent
from app.models import AgentContext, MovieCandidate, SourcePayload

if TYPE_CHECKING:
    from app.services.memory_store import MemoryStore


class NationalFilmRegistryAgent(MovieAgent):
    """Agent that provides National Film Registry preserved films."""

    name = "film_registry"

    def __init__(self, dataset_path: Path, memory_store: "MemoryStore | None" = None):
        self._dataset_path = dataset_path
        self._memory_store = memory_store

    async def collect(self, context: AgentContext) -> SourcePayload:
        rows = self._load_data()
        if not rows:
            return SourcePayload(metadata={"notes": "National Film Registry dataset missing"})

        movies: list[MovieCandidate] = []
        for row in rows:
            title = row.get("title")
            year = row.get("year")
            inducted = row.get("inducted", "")
            if not title:
                continue
            evidence = ["Library of Congress National Film Registry"]
            if inducted:
                evidence.append(f"Inducted {inducted}")
            movies.append(
                MovieCandidate(
                    movie_id=f"film_registry:{title.lower().replace(' ', '_')}",
                    title=title,
                    year=year,
                    source_tags=["film_registry", "preserved", "classic"],
                    evidence=evidence,
                )
            )

        return SourcePayload(
            movies=movies,
            metadata={"notes": f"Loaded {len(movies)} National Film Registry entries"},
        )

    def _load_data(self) -> list[dict]:
        if self._memory_store:
            try:
                cached_data, _ = self._memory_store.get_catalog_cache("film_registry")
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
