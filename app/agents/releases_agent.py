from __future__ import annotations

import json
from pathlib import Path

from app.agents.base import MovieAgent
from app.clients.releases_client import ReleasesClient
from app.models import AgentContext, MovieCandidate, SourcePayload


class ReleasesAgent(MovieAgent):
    name = "releases"

    def __init__(self, releases_url: str | None, timeout_seconds: float, fallback_dataset_path: Path):
        self._releases_url = releases_url
        self._client = ReleasesClient(timeout_seconds=timeout_seconds)
        self._fallback_dataset_path = fallback_dataset_path

    async def collect(self, context: AgentContext) -> SourcePayload:
        if self._releases_url:
            try:
                rows = await self._client.upcoming_movies(self._releases_url)
                movies = [self._to_candidate(row, prefix="releases") for row in rows]
                return SourcePayload(
                    movies=movies,
                    metadata={"notes": f"Fetched {len(movies)} Releases.com entries"},
                )
            except Exception as exc:  # noqa: BLE001
                if self._fallback_dataset_path.exists():
                    rows = json.loads(self._fallback_dataset_path.read_text())
                    movies = [self._to_candidate(row, prefix="releases_seed") for row in rows]
                    return SourcePayload(
                        movies=movies,
                        metadata={
                            "notes": (
                                "Releases.com live fetch failed; "
                                f"using local seed dataset ({exc})"
                            )
                        },
                    )
                return SourcePayload(metadata={"notes": f"Releases.com fetch failed: {exc}"})

        if self._fallback_dataset_path.exists():
            rows = json.loads(self._fallback_dataset_path.read_text())
            movies = [self._to_candidate(row, prefix="releases_seed") for row in rows]
            return SourcePayload(
                movies=movies,
                metadata={"notes": "Releases.com URL missing, using local seed dataset"},
            )

        return SourcePayload(metadata={"notes": "No Releases.com URL and no local dataset"})

    @staticmethod
    def _to_candidate(row: dict, prefix: str) -> MovieCandidate:
        title = row.get("title", "Unknown")
        slug = (
            row.get("url", "")
            .rstrip("/")
            .split("/")[-1]
            .replace(" ", "_")
            .lower()
            or title.lower().replace(" ", "_")
        )
        release_date = row.get("release_date")
        evidence = ["Listed on Releases.com"]
        if release_date:
            evidence = [f"Releases.com upcoming date: {release_date}"]

        return MovieCandidate(
            movie_id=f"{prefix}:{slug}",
            title=title,
            year=row.get("year"),
            release_date=release_date,
            poster_url=row.get("poster_url") or row.get("image"),
            overview=row.get("overview"),
            source_tags=["releases"],
            evidence=evidence,
        )
