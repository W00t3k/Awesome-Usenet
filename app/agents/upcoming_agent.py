from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from app.agents.base import MovieAgent
from app.clients.tmdb_client import TMDBClient
from app.models import AgentContext, MovieCandidate, SourcePayload

if TYPE_CHECKING:
    from app.services.swarm_context import SwarmContext

logger = logging.getLogger(__name__)


TMDB_GENRE_MAP: dict[int, str] = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime",
    99: "Documentary", 18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History",
    27: "Horror", 10402: "Music", 9648: "Mystery", 10749: "Romance",
    878: "Sci-Fi", 10770: "TV Movie", 53: "Thriller", 10752: "War", 37: "Western",
}


class UpcomingAgent(MovieAgent):
    name = "upcoming"
    supports_llm = True  # Enable LLM for smart ranking

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

    async def collect(self, context: AgentContext | SwarmContext) -> SourcePayload:
        if self._tmdb_client:
            # Fetch upcoming and now playing in parallel (reduced pages for speed)
            upcoming_rows, now_playing_rows = await asyncio.gather(
                self._tmdb_client.upcoming_movies_all(max_pages=3),
                self._tmdb_client.now_playing_all(max_pages=2),
            )

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

            # Use LLM to rank movies if available
            llm_enabled = hasattr(context, "ollama_client") and context.ollama_client is not None
            if llm_enabled and len(movies) > 10:
                # Convert to dicts for ranking
                movie_dicts = [
                    {"title": m.title, "year": m.year, "genres": m.genres}
                    for m in movies
                ]
                ranked_dicts = await context.rank_candidates(movie_dicts, "user preferences")
                # Reorder movies based on ranking
                title_to_movie = {m.title: m for m in movies}
                ranked_movies = []
                for d in ranked_dicts:
                    if d["title"] in title_to_movie:
                        ranked_movies.append(title_to_movie[d["title"]])
                if ranked_movies:
                    movies = ranked_movies
                    logger.debug(f"LLM-ranked {len(movies)} upcoming movies")

            return SourcePayload(
                movies=movies,
                metadata={
                    "notes": f"Fetched {len(movies)} movies from TMDB (upcoming + now playing)",
                    "upcoming_count": len(upcoming_rows),
                    "now_playing_count": len(now_playing_rows),
                    "llm_ranked": llm_enabled,
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
