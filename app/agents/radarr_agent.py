from __future__ import annotations

from app.agents.base import MovieAgent
from app.clients.radarr_client import RadarrClient
from app.models import AgentContext, MovieCandidate, SourcePayload


class RadarrAgent(MovieAgent):
    name = "radarr"

    def __init__(self, base_url: str, api_key: str | None, timeout_seconds: float):
        self._client = (
            RadarrClient(base_url=base_url, api_key=api_key, timeout_seconds=timeout_seconds)
            if api_key
            else None
        )

    async def collect(self, context: AgentContext) -> SourcePayload:
        if not self._client:
            return SourcePayload(metadata={"notes": "RADARR_API_KEY missing; skipping Radarr lookup"})

        rows = await self._client.movies()
        movies: list[MovieCandidate] = []
        for row in rows:
            title = row.get("title")
            if not title:
                continue
            movies.append(
                MovieCandidate(
                    movie_id=f"radarr:{row.get('id', title.lower().replace(' ', '_'))}",
                    title=title,
                    year=row.get("year"),
                    release_date=row.get("inCinemas") or row.get("digitalRelease"),
                    overview=row.get("overview"),
                    source_tags=["radarr"],
                    evidence=["Tracked in Radarr"],
                    available_on_radarr=True,
                )
            )

        return SourcePayload(
            movies=movies,
            metadata={"notes": f"Loaded {len(movies)} movies from Radarr"},
        )
