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
            poster_url = None
            for image in row.get("images", []):
                if image.get("coverType") != "poster":
                    continue
                candidate = image.get("remoteUrl") or image.get("url")
                if isinstance(candidate, str) and candidate:
                    poster_url = candidate
                    break
            raw_genres = row.get("genres", [])
            genres = [str(g) for g in raw_genres if isinstance(g, str)] if isinstance(raw_genres, list) else []

            movies.append(
                MovieCandidate(
                    movie_id=f"radarr:{row.get('id', title.lower().replace(' ', '_'))}",
                    title=title,
                    year=row.get("year"),
                    release_date=row.get("inCinemas") or row.get("digitalRelease"),
                    poster_url=poster_url,
                    overview=row.get("overview"),
                    genres=genres,
                    source_tags=["radarr"],
                    evidence=["Tracked in Radarr"],
                    available_on_radarr=True,
                )
            )

        return SourcePayload(
            movies=movies,
            metadata={"notes": f"Loaded {len(movies)} movies from Radarr"},
        )
