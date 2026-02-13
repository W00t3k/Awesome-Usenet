from __future__ import annotations

import json
from pathlib import Path

from app.agents.base import MovieAgent
from app.clients.tmdb_client import TMDBClient
from app.models import AgentContext, MovieCandidate, SourcePayload


class UpcomingAgent(MovieAgent):
    name = "upcoming"

    def __init__(
        self,
        tmdb_api_key: str | None,
        timeout_seconds: float,
        fallback_dataset_path: Path,
    ):
        self._tmdb_client = (
            TMDBClient(api_key=tmdb_api_key, timeout_seconds=timeout_seconds)
            if tmdb_api_key
            else None
        )
        self._fallback_dataset_path = fallback_dataset_path

    async def collect(self, context: AgentContext) -> SourcePayload:
        if self._tmdb_client:
            rows = await self._tmdb_client.upcoming_movies()
            movies = [self._to_candidate(row) for row in rows]
            return SourcePayload(
                movies=movies,
                metadata={"notes": f"Fetched {len(movies)} upcoming movies from TMDB"},
            )

        if self._fallback_dataset_path.exists():
            rows = json.loads(self._fallback_dataset_path.read_text())
            movies = [self._to_candidate(row, prefix="upcoming_seed") for row in rows]
            return SourcePayload(
                movies=movies,
                metadata={"notes": "TMDB API key missing, using local upcoming seed dataset"},
            )

        return SourcePayload(metadata={"notes": "No TMDB key and no local upcoming dataset"})

    @staticmethod
    def _to_candidate(row: dict, prefix: str = "tmdb") -> MovieCandidate:
        title = row.get("title", "Unknown")
        movie_id = row.get("id") or title.lower().replace(" ", "_")
        year = None
        if row.get("release_date"):
            year = int(str(row["release_date"])[:4])

        return MovieCandidate(
            movie_id=f"{prefix}:{movie_id}",
            title=title,
            year=year,
            release_date=row.get("release_date"),
            overview=row.get("overview"),
            source_tags=["upcoming"],
            evidence=[f"Upcoming release: {row.get('release_date', 'unknown date')}"]
            if row.get("release_date")
            else ["Upcoming release"],
        )
