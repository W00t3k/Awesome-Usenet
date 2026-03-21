from __future__ import annotations

import json
from pathlib import Path

from app.agents.base import MovieAgent
from app.clients.rottentomatoes_client import RottenTomatoesClient
from app.models import AgentContext, MovieCandidate, SourcePayload


class RottenTomatoesAgent(MovieAgent):
    name = "rottentomatoes"

    def __init__(self, list_url: str | None, timeout_seconds: float, fallback_dataset_path: Path):
        self._list_url = list_url
        self._client = RottenTomatoesClient(timeout_seconds=timeout_seconds)
        self._fallback_dataset_path = fallback_dataset_path
        self._cache_dataset_path = fallback_dataset_path.with_name("rottentomatoes_cache.json")

    async def collect(self, context: AgentContext) -> SourcePayload:
        if self._list_url:
            try:
                rows = await self._client.browse_movies(self._list_url)
                if rows:
                    self._cache_dataset_path.write_text(json.dumps(rows))
                movies = [self._to_candidate(row, prefix="rt") for row in rows]
                return SourcePayload(
                    movies=movies,
                    metadata={"notes": f"Fetched {len(movies)} Rotten Tomatoes entries"},
                )
            except Exception as exc:  # noqa: BLE001
                if self._cache_dataset_path.exists():
                    rows = json.loads(self._cache_dataset_path.read_text())
                    movies = [self._to_candidate(row, prefix="rt_cache") for row in rows]
                    return SourcePayload(
                        movies=movies,
                        metadata={
                            "notes": (
                                "Rotten Tomatoes live fetch failed; "
                                f"using cached dataset ({exc})"
                            )
                        },
                    )
                if self._fallback_dataset_path.exists():
                    rows = json.loads(self._fallback_dataset_path.read_text())
                    movies = [self._to_candidate(row, prefix="rt_seed") for row in rows]
                    return SourcePayload(
                        movies=movies,
                        metadata={
                            "notes": (
                                "Rotten Tomatoes live fetch failed; "
                                f"using local seed dataset ({exc})"
                            )
                        },
                    )
                return SourcePayload(metadata={"notes": f"Rotten Tomatoes fetch failed: {exc}"})

        if self._cache_dataset_path.exists():
            rows = json.loads(self._cache_dataset_path.read_text())
            movies = [self._to_candidate(row, prefix="rt_cache") for row in rows]
            return SourcePayload(
                movies=movies,
                metadata={"notes": "Rotten Tomatoes URL missing, using cached dataset"},
            )

        if self._fallback_dataset_path.exists():
            rows = json.loads(self._fallback_dataset_path.read_text())
            movies = [self._to_candidate(row, prefix="rt_seed") for row in rows]
            return SourcePayload(
                movies=movies,
                metadata={"notes": "Rotten Tomatoes URL missing, using local seed dataset"},
            )

        return SourcePayload(metadata={"notes": "No Rotten Tomatoes URL and no local dataset"})

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
        tomatometer = row.get("tomatometer")
        review_count = row.get("review_count")

        source_tags = ["rottentomatoes"]
        if isinstance(tomatometer, int):
            if tomatometer >= 95:
                source_tags.append("rt-95plus")
            elif tomatometer >= 90:
                source_tags.append("rt-90plus")
            elif tomatometer >= 80:
                source_tags.append("rt-80plus")

        evidence = ["Listed on Rotten Tomatoes"]
        if tomatometer is not None and review_count is not None:
            evidence = [f"Rotten Tomatoes Tomatometer: {tomatometer}% ({review_count} reviews)"]
        elif tomatometer is not None:
            evidence = [f"Rotten Tomatoes Tomatometer: {tomatometer}%"]

        genres = row.get("genres", [])
        if not isinstance(genres, list):
            genres = []

        return MovieCandidate(
            movie_id=f"{prefix}:{slug}",
            title=title,
            year=row.get("year"),
            poster_url=row.get("poster_url") or row.get("image"),
            rottentomatoes_score=tomatometer if isinstance(tomatometer, int) else None,
            genres=genres,
            source_tags=source_tags,
            evidence=evidence,
        )
