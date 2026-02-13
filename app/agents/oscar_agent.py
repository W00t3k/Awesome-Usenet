from __future__ import annotations

import json
from pathlib import Path

from app.agents.base import MovieAgent
from app.models import AgentContext, MovieCandidate, SourcePayload


class OscarAgent(MovieAgent):
    name = "oscars"

    def __init__(self, dataset_path: Path):
        self._dataset_path = dataset_path

    async def collect(self, context: AgentContext) -> SourcePayload:
        if not self._dataset_path.exists():
            return SourcePayload(metadata={"notes": "Oscars dataset missing"})

        rows = json.loads(self._dataset_path.read_text())
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
            metadata={"notes": f"Loaded {len(rows)} Oscar years from local dataset"},
        )
