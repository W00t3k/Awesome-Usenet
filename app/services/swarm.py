from __future__ import annotations

import asyncio
import time
from datetime import UTC, date, datetime

from app.agents.base import MovieAgent
from app.clients.poster_lookup_client import PosterLookupClient
from app.clients.tmdb_client import TMDBClient
from app.models import MovieCandidate
from app.models import AgentContext, AgentResult, RecommendationResponse, SourcePayload
from app.services.recommender import Recommender


class SwarmOrchestrator:
    def __init__(
        self,
        agents: list[MovieAgent],
        recommender: Recommender,
        poster_lookup_client: PosterLookupClient | None = None,
        tmdb_client: TMDBClient | None = None,
    ):
        self._agents = agents
        self._recommender = recommender
        self._poster_lookup_client = poster_lookup_client
        self._tmdb_client = tmdb_client

    async def collect_sources(
        self,
        user_id: str,
        count: int,
    ) -> tuple[dict[str, list[MovieCandidate]], list[AgentResult]]:
        context = AgentContext(
            user_id=user_id,
            requested_count=count,
            now_iso=datetime.now(UTC).isoformat(),
        )

        tasks = [self._run_agent(agent, context) for agent in self._agents]
        completed = await asyncio.gather(*tasks)

        source_movies: dict[str, list[MovieCandidate]] = {}
        agent_statuses: list[AgentResult] = []

        for agent_name, payload, status in completed:
            source_movies[agent_name] = payload.movies
            agent_statuses.append(status)
        return source_movies, agent_statuses

    async def recommend(self, user_id: str, count: int) -> RecommendationResponse:
        return await self.recommend_filtered(
            user_id=user_id,
            count=count,
            sort_mode=None,
            required_sources=None,
            release_date_from=None,
            release_date_to=None,
        )

    async def _tmdb_discover_for_years(
        self, year_from: int | None, year_to: int | None, count: int,
    ) -> list[MovieCandidate]:
        if not self._tmdb_client:
            return []
        try:
            pages_needed = max(1, (count + 19) // 20)
            all_results: list[dict] = []
            for page in range(1, min(pages_needed, 4) + 1):
                results = await self._tmdb_client.discover_movies(
                    year_from=year_from, year_to=year_to, page=page,
                )
                all_results.extend(results)
            candidates: list[MovieCandidate] = []
            for m in all_results:
                release = m.get("release_date") or ""
                year = int(release[:4]) if len(release) >= 4 else None
                poster_path = m.get("poster_path")
                poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
                vote_avg = m.get("vote_average") or 0
                rt_score = max(0, min(100, int(vote_avg * 10))) if vote_avg else None
                tmdb_id = m.get("id") or 0
                candidates.append(MovieCandidate(
                    movie_id=f"tmdb-{tmdb_id}",
                    title=m.get("title") or "Unknown",
                    year=year,
                    source_tags=["tmdb-discover"],
                    evidence=["TMDB discover"],
                    overview=m.get("overview") or "",
                    poster_url=poster_url,
                    release_date=release or None,
                    rottentomatoes_score=rt_score,
                    genres=[],
                ))
            return candidates
        except Exception:  # noqa: BLE001
            return []

    async def recommend_filtered(
        self,
        user_id: str,
        count: int,
        sort_mode: str | None,
        required_sources: set[str] | None,
        release_date_from: date | None,
        release_date_to: date | None,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> RecommendationResponse:
        source_movies, agent_statuses = await self.collect_sources(user_id=user_id, count=count)

        if year_from is not None or year_to is not None:
            tmdb_movies = await self._tmdb_discover_for_years(year_from, year_to, count)
            if tmdb_movies:
                source_movies["tmdb-discover"] = tmdb_movies

        await self._enrich_source_posters(source_movies, max_items=300)

        recommendations = await self._recommender.rank(
            user_id=user_id,
            source_movies=source_movies,
            top_n=count,
            sort_mode=sort_mode,
            required_sources=required_sources,
            release_date_from=release_date_from,
            release_date_to=release_date_to,
            year_from=year_from,
            year_to=year_to,
        )
        await self._enrich_posters(recommendations)

        return RecommendationResponse(
            generated_at=datetime.now(UTC),
            user_id=user_id,
            recommendations=recommendations,
            agents=agent_statuses,
        )

    @staticmethod
    def _is_placeholder_url(url: str | None) -> bool:
        if not url:
            return True
        lower = url.lower()
        return "example.com" in lower or "placeholder" in lower or "no-image" in lower

    async def _enrich_posters(self, recommendations: list) -> None:
        if not self._poster_lookup_client:
            return

        semaphore = asyncio.Semaphore(10)

        async def enrich(movie: MovieCandidate) -> None:
            needs_poster = self._is_placeholder_url(movie.poster_url)
            needs_overview = not movie.overview
            needs_genres = not movie.genres
            if not needs_poster and not needs_overview and not needs_genres:
                return
            async with semaphore:
                try:
                    info = await self._poster_lookup_client.lookup(movie.title, movie.year)
                except Exception:  # noqa: BLE001
                    return
                if not info:
                    return
                if needs_poster and info.get("poster_url"):
                    movie.poster_url = info["poster_url"]
                if needs_overview and info.get("overview"):
                    movie.overview = info["overview"]
                if needs_genres:
                    # Prefer full genres list from TMDB
                    if info.get("genres"):
                        movie.genres = info["genres"]
                    elif info.get("genre"):
                        movie.genres = [info["genre"]]

        await asyncio.gather(*(enrich(rec.movie) for rec in recommendations))

    async def _enrich_source_posters(
        self, source_movies: dict[str, list[MovieCandidate]], max_items: int = 80,
    ) -> None:
        if not self._poster_lookup_client:
            return

        needs_enrichment: list[MovieCandidate] = []
        for movies in source_movies.values():
            for movie in movies:
                if self._is_placeholder_url(movie.poster_url):
                    needs_enrichment.append(movie)

        if not needs_enrichment:
            return

        semaphore = asyncio.Semaphore(10)

        async def enrich(movie: MovieCandidate) -> None:
            async with semaphore:
                try:
                    info = await self._poster_lookup_client.lookup(movie.title, movie.year)
                except Exception:  # noqa: BLE001
                    return
                if not info:
                    return
                if self._is_placeholder_url(movie.poster_url) and info.get("poster_url"):
                    movie.poster_url = info["poster_url"]
                if not movie.overview and info.get("overview"):
                    movie.overview = info["overview"]
                if not movie.genres:
                    # Prefer full genres list from TMDB
                    if info.get("genres"):
                        movie.genres = info["genres"]
                    elif info.get("genre"):
                        movie.genres = [info["genre"]]

        await asyncio.gather(*(enrich(m) for m in needs_enrichment[:max_items]))

    async def fetch_movies_for_year(self, year: int, max_pages: int = 10) -> list[MovieCandidate]:
        """Fetch ALL movies from TMDB for a specific year."""
        if not self._tmdb_client:
            return []

        try:
            results = await self._tmdb_client.discover_movies_for_year(
                year=year, max_pages=max_pages
            )
            candidates: list[MovieCandidate] = []
            for m in results:
                release = m.get("release_date") or ""
                movie_year = int(release[:4]) if len(release) >= 4 else year
                poster_path = m.get("poster_path")
                poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
                vote_avg = m.get("vote_average") or 0
                rt_score = max(0, min(100, int(vote_avg * 10))) if vote_avg else None
                tmdb_id = m.get("id") or 0

                candidates.append(MovieCandidate(
                    movie_id=f"tmdb-year-{tmdb_id}",
                    title=m.get("title") or "Unknown",
                    year=movie_year,
                    source_tags=["tmdb-discover", f"year-{year}"],
                    evidence=[f"TMDB discover for {year}"],
                    overview=m.get("overview") or "",
                    poster_url=poster_url,
                    release_date=release or None,
                    rottentomatoes_score=rt_score,
                    genres=[],
                ))
            return candidates
        except Exception:  # noqa: BLE001
            return []

    async def _run_agent(
        self,
        agent: MovieAgent,
        context: AgentContext,
    ) -> tuple[str, SourcePayload, AgentResult]:
        started = time.perf_counter()
        try:
            payload = await agent.collect(context)
            runtime_ms = int((time.perf_counter() - started) * 1000)
            notes = payload.metadata.get("notes") if isinstance(payload.metadata, dict) else None
            lowered_notes = (notes or "").lower()
            status = "success"
            if payload.movies == [] and any(
                marker in lowered_notes for marker in ["missing", "skip", "no "]
            ):
                status = "skipped"

            return (
                agent.name,
                payload,
                AgentResult(
                    agent=agent.name,
                    status=status,
                    runtime_ms=runtime_ms,
                    item_count=len(payload.movies),
                    notes=notes,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            runtime_ms = int((time.perf_counter() - started) * 1000)
            return (
                agent.name,
                SourcePayload(),
                AgentResult(
                    agent=agent.name,
                    status="error",
                    runtime_ms=runtime_ms,
                    item_count=0,
                    notes=str(exc),
                ),
            )
