from __future__ import annotations

import hashlib

from app.agents.base import MovieAgent
from app.clients.usenet_client import UsenetClient
from app.models import AgentContext, MovieCandidate, SourcePayload


class UsenetAgent(MovieAgent):
    name = "usenet"

    def __init__(self, base_url: str, api_key: str | None, timeout_seconds: float):
        self._client = (
            UsenetClient(base_url=base_url, api_key=api_key, timeout_seconds=timeout_seconds)
            if api_key
            else None
        )

    async def collect(self, context: AgentContext) -> SourcePayload:
        if not self._client:
            return SourcePayload(metadata={"notes": "USENET_API_KEY missing; skipping Usenet lookup"})

        rows = await self._client.movie_search()
        movies: list[MovieCandidate] = []
        for row in rows:
            title = (row.get("title") or "").strip()
            if not title:
                continue

            looks_unusual = any(
                marker in title.lower()
                for marker in ["restored", "criterion", "director's cut", "rare", "unrated"]
            )
            if not looks_unusual:
                continue

            movies.append(
                MovieCandidate(
                    movie_id=f"usenet:{hashlib.sha1(title.encode('utf-8')).hexdigest()[:12]}",
                    title=title,
                    source_tags=["usenet", "unusual-discovery"],
                    evidence=["Matched unusual release markers on Usenet feed"],
                    available_on_usenet=True,
                )
            )

        return SourcePayload(
            movies=movies,
            metadata={"notes": f"Loaded {len(movies)} unusual candidates from Usenet feed"},
        )
