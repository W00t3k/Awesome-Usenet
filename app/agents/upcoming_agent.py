from __future__ import annotations

import json
from pathlib import Path

from app.agents.base import MovieAgent
from app.clients.tmdb_client import TMDBClient
from app.models import AgentContext, MovieCandidate, SourcePayload


TMDB_GENRE_MAP: dict[int, str] = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime",
    99: "Documentary", 18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History",
    27: "Horror", 10402: "Music", 9648: "Mystery", 10749: "Romance",
    878: "Sci-Fi", 10770: "TV Movie", 53: "Thriller", 10752: "War", 37: "Western",
}


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
            # Fetch ALL upcoming movies (paginated)
            upcoming_rows = await self._tmdb_client.upcoming_movies_all(max_pages=10)
            # Also fetch now playing for recent releases
            now_playing_rows = await self._tmdb_client.now_playing_all(max_pages=5)

            movies: list[MovieCandidate] = []
            seen_ids: set[int] = set()

            # Add upcoming movies
            for row in upcoming_rows:
                tmdb_id = row.get("id")
                if tmdb_id and tmdb_id not in seen_ids:
                    seen_ids.add(tmdb_id)
                    movies.append(self._to_candidate(row, tags=["upcoming", "unreleased"]))

            # Add now playing (recent releases)
            for row in now_playing_rows:
                tmdb_id = row.get("id")
                if tmdb_id and tmdb_id not in seen_ids:
                    seen_ids.add(tmdb_id)
                    movies.append(self._to_candidate(row, tags=["upcoming", "now-playing"]))

            return SourcePayload(
                movies=movies,
                metadata={
                    "notes": f"Fetched {len(movies)} movies from TMDB (upcoming + now playing)",
                    "upcoming_count": len(upcoming_rows),
                    "now_playing_count": len(now_playing_rows),
                },
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
    def _to_candidate(
        row: dict, prefix: str = "tmdb", tags: list[str] | None = None
    ) -> MovieCandidate:
        title = row.get("title", "Unknown")
        movie_id = row.get("id") or title.lower().replace(" ", "_")
        year = None
        if row.get("release_date"):
            year = int(str(row["release_date"])[:4])

        poster_url = row.get("poster_url")
        poster_path = row.get("poster_path")
        if not poster_url and isinstance(poster_path, str) and poster_path:
            poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"

        genres = [
            TMDB_GENRE_MAP[gid]
            for gid in (row.get("genre_ids") or [])
            if isinstance(gid, int) and gid in TMDB_GENRE_MAP
        ]

        source_tags = tags if tags else ["upcoming"]

        return MovieCandidate(
            movie_id=f"{prefix}:{movie_id}",
            title=title,
            year=year,
            release_date=row.get("release_date"),
            poster_url=poster_url,
            overview=row.get("overview"),
            genres=genres,
            source_tags=source_tags,
            evidence=[f"Upcoming release: {row.get('release_date', 'unknown date')}"]
            if row.get("release_date")
            else ["Upcoming release"],
        )
