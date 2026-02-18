from __future__ import annotations

import json
from pathlib import Path

from app.agents.base import MovieAgent
from app.clients.rogerebert_client import RogerEbertClient
from app.models import AgentContext, MovieCandidate, SourcePayload


class RogerEbertAgent(MovieAgent):
    name = "rogerebert"

    def __init__(self, reviews_url: str | None, timeout_seconds: float, fallback_dataset_path: Path):
        self._reviews_url = reviews_url
        self._client = RogerEbertClient(timeout_seconds=timeout_seconds)
        self._fallback_dataset_path = fallback_dataset_path
        self._allowed_years = {2025, 2026}

    async def collect(self, context: AgentContext) -> SourcePayload:
        # Try RSS feed first (more reliable, not blocked by 403)
        try:
            rows = await self._client.reviews_from_rss(years=self._allowed_years)
            if rows:
                movies = self._to_candidates(rows, prefix="rogerebert")
                return SourcePayload(
                    movies=movies,
                    metadata={
                        "notes": (
                            f"Fetched {len(movies)} RogerEbert reviews from RSS feed "
                            f"(years: {', '.join(str(y) for y in sorted(self._allowed_years))})"
                        )
                    },
                )
        except Exception:  # noqa: BLE001
            pass

        # Fallback to web scraping if RSS fails
        if self._reviews_url:
            try:
                # Fetch ALL reviews for 2025-2026 by paginating
                rows = await self._client.all_reviews_for_years(
                    base_url=self._reviews_url,
                    years=self._allowed_years,
                    max_pages=25,  # Up to 25 pages to get all recent reviews
                )
                movies = self._to_candidates(rows, prefix="rogerebert")
                return SourcePayload(
                    movies=movies,
                    metadata={
                        "notes": (
                            f"Fetched {len(movies)} RogerEbert reviews "
                            f"(years: {', '.join(str(y) for y in sorted(self._allowed_years))}, "
                            f"paginated)"
                        )
                    },
                )
            except Exception as exc:  # noqa: BLE001
                if self._fallback_dataset_path.exists():
                    rows = json.loads(self._fallback_dataset_path.read_text())
                    movies = self._to_candidates(rows, prefix="rogerebert_seed")
                    return SourcePayload(
                        movies=movies,
                        metadata={
                            "notes": (
                                "RogerEbert fallback mode: using local seed dataset "
                                f"(live site blocked/unavailable: {exc})"
                            )
                        },
                    )
                return SourcePayload(metadata={"notes": f"RogerEbert fetch failed: {exc}"})

        if self._fallback_dataset_path.exists():
            rows = json.loads(self._fallback_dataset_path.read_text())
            movies = self._to_candidates(rows, prefix="rogerebert_seed")
            return SourcePayload(
                movies=movies,
                metadata={
                    "notes": (
                        "RogerEbert URL missing, using local seed dataset "
                        "(filtered to 2025-2026)"
                    )
                },
            )

        return SourcePayload(metadata={"notes": "No RogerEbert URL and no local dataset"})

    def _to_candidates(self, rows: list[dict], prefix: str) -> list[MovieCandidate]:
        movies: list[MovieCandidate] = []
        for row in rows:
            title = row.get("title")
            year = row.get("year")
            if not title or not isinstance(year, int) or year not in self._allowed_years:
                continue

            slug = (
                row.get("url", "")
                .rstrip("/")
                .split("/")[-1]
                .replace(" ", "_")
                .lower()
                or title.lower().replace(" ", "_")
            )
            release_date = row.get("release_date")
            evidence = ["Listed on RogerEbert.com"]
            if release_date:
                evidence = [f"RogerEbert review date: {release_date}"]

            movies.append(
                MovieCandidate(
                    movie_id=f"{prefix}:{slug}",
                    title=title,
                    year=year,
                    release_date=release_date,
                    poster_url=row.get("poster_url") or row.get("image"),
                    rogerebert_score=row.get("rating"),
                    overview=row.get("overview"),
                    source_tags=["rogerebert", "critic-review"],
                    evidence=evidence,
                )
            )
        return movies
