from __future__ import annotations

import json
from pathlib import Path

from app.agents.base import MovieAgent
from app.clients.rogerebert_client import RogerEbertClient
from app.config import limits
from app.models import AgentContext, MovieCandidate, SourcePayload


class RogerEbertAgent(MovieAgent):
    name = "rogerebert"

    def __init__(self, reviews_url: str | None, timeout_seconds: float, fallback_dataset_path: Path):
        self._reviews_url = reviews_url
        self._client = RogerEbertClient(timeout_seconds=timeout_seconds)
        self._fallback_dataset_path = fallback_dataset_path
        # Use configurable year range from limits (default: 1900 to current+2)
        self._min_year = limits.min_year
        self._max_year = limits.get_max_year()
        # None means accept all years; otherwise build a set
        self._allowed_years: set[int] | None = None
        if self._min_year is not None or self._max_year is not None:
            min_y = self._min_year or 1900
            max_y = self._max_year or 2030
            self._allowed_years = set(range(min_y, max_y + 1))

    def _year_range_str(self) -> str:
        """Return a human-readable year range string."""
        if self._allowed_years is None:
            return "all years"
        return f"{self._min_year}-{self._max_year}"

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
                            f"(years: {self._year_range_str()})"
                        )
                    },
                )
        except Exception:  # noqa: BLE001
            pass

        # Fallback to web scraping if RSS fails
        if self._reviews_url:
            try:
                # Fetch reviews with configurable pagination
                rows = await self._client.all_reviews_for_years(
                    base_url=self._reviews_url,
                    years=self._allowed_years,
                    max_pages=limits.rogerebert_max_pages,
                )
                movies = self._to_candidates(rows, prefix="rogerebert")
                return SourcePayload(
                    movies=movies,
                    metadata={
                        "notes": (
                            f"Fetched {len(movies)} RogerEbert reviews "
                            f"(years: {self._year_range_str()}, paginated)"
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
                        f"RogerEbert URL missing, using local seed dataset "
                        f"(years: {self._year_range_str()})"
                    )
                },
            )

        return SourcePayload(metadata={"notes": "No RogerEbert URL and no local dataset"})

    def _to_candidates(self, rows: list[dict], prefix: str) -> list[MovieCandidate]:
        movies: list[MovieCandidate] = []
        for row in rows:
            title = row.get("title")
            year = row.get("year")
            if not title or not isinstance(year, int):
                continue
            # If allowed_years is None, accept all years; otherwise check membership
            if self._allowed_years is not None and year not in self._allowed_years:
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
