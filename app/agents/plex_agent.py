from __future__ import annotations

from app.agents.base import MovieAgent
from app.clients.plex_client import PlexClient
from app.models import AgentContext, MovieCandidate, SourcePayload


class PlexAgent(MovieAgent):
    name = "plex"

    def __init__(self, base_url: str, token: str | None, timeout_seconds: float):
        self._client = (
            PlexClient(base_url=base_url, token=token, timeout_seconds=timeout_seconds)
            if token
            else None
        )

    async def collect(self, context: AgentContext) -> SourcePayload:
        if not self._client:
            return SourcePayload(metadata={"notes": "PLEX_TOKEN missing; skipping Plex lookup"})

        rows = await self._client.library_movies()
        movies: list[MovieCandidate] = []
        for row in rows:
            title = row.get("title")
            if not title:
                continue
            movies.append(
                MovieCandidate(
                    movie_id=f"plex:{row.get('ratingKey', title.lower().replace(' ', '_'))}",
                    title=title,
                    year=row.get("year"),
                    overview=row.get("summary"),
                    source_tags=["plex"],
                    evidence=["Already in Plex library"],
                    available_on_plex=True,
                )
            )

        return SourcePayload(
            movies=movies,
            metadata={"notes": f"Loaded {len(movies)} movies from Plex"},
        )
