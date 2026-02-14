from __future__ import annotations

import json
from pathlib import Path

from app.agents.base import MovieAgent
from app.models import AgentContext, MovieCandidate, SourcePayload


class CriterionAgent(MovieAgent):
    name = "criterion"

    def __init__(self, dataset_path: Path):
        self._dataset_path = dataset_path

    async def collect(self, context: AgentContext) -> SourcePayload:
        if not self._dataset_path.exists():
            return SourcePayload(metadata={"notes": "Criterion dataset missing"})

        rows = json.loads(self._dataset_path.read_text())
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
            metadata={"notes": f"Loaded {len(movies)} Criterion entries from local dataset"},
        )
