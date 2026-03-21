from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from app.agents.base import MovieAgent
from app.clients.llm_client import UnifiedLLMClient
from app.clients.poster_lookup_client import PosterLookupClient
from app.clients.tmdb_client import TMDBClient
from app.models import MovieCandidate
from app.models import AgentContext, AgentResult, RecommendationResponse, SourcePayload
from app.services.recommender import Recommender
from app.services.swarm_context import SwarmContext, UserPreferences, build_user_preferences

if TYPE_CHECKING:
    from app.services.memory_store import MemoryStore

logger = logging.getLogger(__name__)


# Default TTLs for different cache types (in seconds)
DEFAULT_RECOMMENDATION_CACHE_TTL = 300  # 5 minutes
DEFAULT_AGENT_CACHE_TTL = 300  # 5 minutes

# Per-agent TTL overrides (in seconds)
# NOTE: Agent names must match exactly (use underscores, not hyphens)
AGENT_CACHE_TTLS: dict[str, int] = {
    # Static data agents - cache longer (1 hour)
    "oscars": 3600,
    "criterion": 3600,
    "imdb_top250": 3600,
    "afi100": 3600,
    "cannes": 3600,
    "ghibli": 3600,
    "sundance": 3600,
    "bafta": 3600,
    "golden_globes": 3600,
    "blumhouse": 3600,
    "marvel_dc": 3600,
    "letterboxd": 3600,
    "mubi": 3600,
    "film_registry": 3600,
    "metacritic": 3600,
    "boxoffice": 3600,
    "hidden_gems": 3600,
    "directors": 3600,
    "decades": 3600,
    "sight_sound": 3600,
    "pixar": 3600,
    "disney": 3600,
    "horror_classics": 3600,
    "scifi": 3600,
    "anime": 3600,
    "korean_cinema": 3600,
    "film_noir": 3600,
    "neon": 3600,
    "a24": 3600,
    # Live agents - shorter cache (10 minutes)
    "rottentomatoes": 600,
    "rogerebert": 600,
    "releases": 600,
    "upcoming": 600,
    "plex": 600,
    # New releases - very short cache (5 minutes)
    "nzbgeek": 300,
    "drunkenslug": 300,
    "usenet": 300,
}


class SwarmOrchestrator:
    def __init__(
        self,
        agents: list[MovieAgent],
        recommender: Recommender,
        poster_lookup_client: PosterLookupClient | None = None,
        tmdb_client: TMDBClient | None = None,
        llm_client: UnifiedLLMClient | None = None,
        memory_store: MemoryStore | None = None,
    ):
        self._agents = agents
        self._recommender = recommender
        self._poster_lookup_client = poster_lookup_client
        self._tmdb_client = tmdb_client
        self._llm_client = llm_client
        self._memory_store = memory_store

        # Phase 1: Recommendation response cache
        # Stores (cached_at_timestamp, RecommendationResponse) tuples
        self._recommendation_cache: dict[str, tuple[float, RecommendationResponse]] = {}
        self._recommendation_cache_ttl = DEFAULT_RECOMMENDATION_CACHE_TTL

        # Phase 2: Agent source cache
        # Stores (cached_at_timestamp, SourcePayload) tuples per agent
        self._agent_cache: dict[str, tuple[float, SourcePayload]] = {}

        # Phase 5: LLM explanation memoization
        # Stores explanation strings by (title:year:genres) key
        self._explanation_cache: dict[str, str] = {}

    def _recommendation_cache_key(
        self,
        user_id: str,
        count: int,
        sort_mode: str | None,
        required_sources: set[str] | None,
        release_date_from: date | None,
        release_date_to: date | None,
        year_from: int | None,
        year_to: int | None,
    ) -> str:
        """Generate a cache key for recommendation requests."""
        # Note: sort_mode excluded - sorting happens client-side for flexibility
        parts = [
            f"user:{user_id}",
            f"count:{count}",
            f"sources:{','.join(sorted(required_sources)) if required_sources else 'all'}",
            f"date_from:{release_date_from.isoformat() if release_date_from else 'none'}",
            f"date_to:{release_date_to.isoformat() if release_date_to else 'none'}",
            f"year_from:{year_from if year_from is not None else 'none'}",
            f"year_to:{year_to if year_to is not None else 'none'}",
        ]
        key_str = "|".join(parts)
        return hashlib.md5(key_str.encode()).hexdigest()

    def _is_recommendation_cache_valid(self, cache_key: str) -> bool:
        """Check if cached recommendation is still valid (not expired)."""
        if cache_key not in self._recommendation_cache:
            return False
        cached_at, _ = self._recommendation_cache[cache_key]
        return (time.time() - cached_at) < self._recommendation_cache_ttl

    def get_cached_recommendations(self, user_id: str, count: int) -> RecommendationResponse | None:
        """Get cached recommendations if available."""
        cache_key = self._recommendation_cache_key(user_id, count, None, None, None, None, None, None)
        if self._is_recommendation_cache_valid(cache_key):
            _, response = self._recommendation_cache[cache_key]
            return response
        return None

    async def stream_agent_updates(self, user_id: str, count: int):
        """Stream agent updates as they complete for real-time UI updates."""
        context = AgentContext(
            user_id=user_id,
            requested_count=count,
            now_iso=datetime.now(UTC).isoformat(),
        )

        # Track which agents need to run (not cached or expired)
        agents_to_run = []
        cached_results = []
        now = time.time()

        for agent in self._agents:
            cache_key = agent.name
            ttl = self._get_agent_cache_ttl(agent.name)
            if cache_key in self._agent_cache:
                cached_at, payload = self._agent_cache[cache_key]
                if now - cached_at < ttl:
                    cached_results.append((agent.name, payload))
                    continue
            agents_to_run.append(agent)

        # Yield cached agent results first
        for agent_name, payload in cached_results:
            yield {
                "agent": agent_name,
                "status": "cached",
                "movies": len(payload.movies) if payload and payload.movies else 0,
            }

        # Run remaining agents and yield updates as they complete
        if agents_to_run:
            tasks = {
                asyncio.create_task(self._run_single_agent(agent, context)): agent
                for agent in agents_to_run
            }

            for coro in asyncio.as_completed(tasks.keys()):
                try:
                    agent_name, payload, elapsed = await coro
                    # Cache the result
                    self._agent_cache[agent_name] = (time.time(), payload)
                    yield {
                        "agent": agent_name,
                        "status": "complete",
                        "movies": len(payload.movies) if payload and payload.movies else 0,
                        "elapsed_ms": round(elapsed * 1000),
                    }
                except Exception as e:
                    yield {
                        "agent": "unknown",
                        "status": "error",
                        "error": str(e),
                    }

    async def _run_single_agent(self, agent, context) -> tuple[str, SourcePayload | None, float]:
        """Run a single agent and return (name, payload, elapsed_time)."""
        start = time.time()
        try:
            payload = await asyncio.wait_for(agent.collect(context), timeout=8.0)
            return (agent.name, payload, time.time() - start)
        except asyncio.TimeoutError:
            return (agent.name, None, time.time() - start)
        except Exception:
            return (agent.name, None, time.time() - start)

    def _get_agent_cache_ttl(self, agent_name: str) -> int:
        """Get TTL for a specific agent's cache."""
        return AGENT_CACHE_TTLS.get(agent_name.lower(), DEFAULT_AGENT_CACHE_TTL)

    def _is_agent_cache_valid(self, agent_name: str) -> bool:
        """Check if cached agent result is still valid (not expired)."""
        if agent_name not in self._agent_cache:
            return False
        cached_at, _ = self._agent_cache[agent_name]
        ttl = self._get_agent_cache_ttl(agent_name)
        return (time.time() - cached_at) < ttl

    def clear_caches(self) -> dict[str, int]:
        """Clear all caches and return counts of cleared items."""
        rec_count = len(self._recommendation_cache)
        agent_count = len(self._agent_cache)
        explanation_count = len(self._explanation_cache)

        self._recommendation_cache.clear()
        self._agent_cache.clear()
        self._explanation_cache.clear()

        logger.info(
            "Cleared caches: %d recommendations, %d agents, %d explanations",
            rec_count, agent_count, explanation_count,
        )
        return {
            "recommendations": rec_count,
            "agents": agent_count,
            "explanations": explanation_count,
        }

    def get_cache_stats(self) -> dict[str, any]:
        """Get current cache statistics."""
        now = time.time()
        valid_recs = sum(
            1 for key in self._recommendation_cache
            if self._is_recommendation_cache_valid(key)
        )
        valid_agents = sum(
            1 for name in self._agent_cache
            if self._is_agent_cache_valid(name)
        )
        return {
            "recommendation_cache": {
                "total": len(self._recommendation_cache),
                "valid": valid_recs,
                "ttl_seconds": self._recommendation_cache_ttl,
            },
            "agent_cache": {
                "total": len(self._agent_cache),
                "valid": valid_agents,
                "agents": list(self._agent_cache.keys()),
            },
            "explanation_cache": {
                "total": len(self._explanation_cache),
            },
        }

    def _build_swarm_context(self, user_id: str, count: int) -> SwarmContext:
        """Build SwarmContext with user preferences for LLM-enabled agents."""
        user_prefs = UserPreferences()

        # Load user preferences from feedback history if memory store available
        if self._memory_store:
            try:
                feedback_rows = self._memory_store.recent_feedback(user_id=user_id, limit=100)
                if feedback_rows:
                    # Convert FeedbackRow objects to dicts
                    rows_as_dicts = [
                        {
                            "title": row.title,
                            "liked": row.liked,
                            "genres_json": json.dumps(row.genres),  # Convert list back to JSON
                            "year": row.year,
                        }
                        for row in feedback_rows
                    ]
                    user_prefs = build_user_preferences(rows_as_dicts)
                    logger.debug(f"Built preferences for {user_id}: {len(user_prefs.liked_titles)} liked titles")
            except Exception as e:
                logger.debug(f"Could not load user preferences: {e}")

        return SwarmContext(
            user_id=user_id,
            requested_count=count,
            now_iso=datetime.now(UTC).isoformat(),
            llm_client=self._llm_client,
            user_preferences=user_prefs,
        )

    async def collect_sources(
        self,
        user_id: str,
        count: int,
    ) -> tuple[dict[str, list[MovieCandidate]], list[AgentResult]]:
        # Build both context types
        basic_context = AgentContext(
            user_id=user_id,
            requested_count=count,
            now_iso=datetime.now(UTC).isoformat(),
        )
        swarm_context = self._build_swarm_context(user_id, count)

        # Run agents with appropriate context based on supports_llm
        tasks = []
        for agent in self._agents:
            ctx = swarm_context if agent.supports_llm else basic_context
            tasks.append(self._run_agent(agent, ctx))

        completed = await asyncio.gather(*tasks)
        # SKIP LLM reasoning annotation - too slow
        # await self._annotate_agent_reasoning(completed)
        # Use simple reasoning instead
        for agent_name, payload, status in completed:
            status.reasoning = f"{status.item_count} movies from {agent_name}"

        source_movies: dict[str, list[MovieCandidate]] = {}
        agent_statuses: list[AgentResult] = []

        for agent_name, payload, status in completed:
            for movie in payload.movies:
                self._normalize_movie(movie)
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
        # Phase 1: Check recommendation cache first
        cache_key = self._recommendation_cache_key(
            user_id, count, sort_mode, required_sources,
            release_date_from, release_date_to, year_from, year_to,
        )
        # Log the request parameters for debugging
        print(f"[CACHE] Request: user={user_id[:20]}... count={count} sort={sort_mode} key={cache_key[:8]}")

        if self._is_recommendation_cache_valid(cache_key):
            _, cached_response = self._recommendation_cache[cache_key]
            print(f"[CACHE] HIT! Returning {len(cached_response.recommendations)} cached movies")
            return cached_response

        print(f"[CACHE] MISS - computing recommendations...")

        # Cache miss - compute recommendations
        start_time = time.time()

        t1 = time.time()
        source_movies, agent_statuses = await self.collect_sources(user_id=user_id, count=count)
        print(f"[TIMING] collect_sources: {time.time()-t1:.2f}s")

        if year_from is not None or year_to is not None:
            tmdb_movies = await self._tmdb_discover_for_years(year_from, year_to, count)
            if tmdb_movies:
                source_movies["tmdb-discover"] = tmdb_movies

        self._apply_local_streaming_markers(source_movies)
        # Enrich posters for top items (async but quick with cache)
        await self._enrich_source_posters(source_movies, max_items=200)

        t2 = time.time()
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
        print(f"[TIMING] rank: {time.time()-t2:.2f}s")

        # Deterministic scores (fast)
        t3 = time.time()
        for rec in recommendations:
            rec.score = round(self._deterministic_front_score(rec), 2)
        print(f"[TIMING] scores: {time.time()-t3:.2f}s")

        # FAST: Use static explanations first (instant)
        for rec in recommendations:
            movie = rec.movie
            sources = ", ".join(movie.source_tags[:3]) if movie.source_tags else "multiple sources"
            genres = ", ".join(movie.genres[:2]) if movie.genres else ""
            rec.explanation = f"From {sources}." + (f" {genres}." if genres else "")

        response = RecommendationResponse(
            generated_at=datetime.now(UTC),
            user_id=user_id,
            recommendations=recommendations,
            agents=agent_statuses,
        )

        # Cache the response
        elapsed = time.time() - start_time
        self._recommendation_cache[cache_key] = (time.time(), response)
        logger.info(
            "Cached recommendations for key %s (computed in %.2fs, %d movies)",
            cache_key[:8], elapsed, len(recommendations),
        )

        return response

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
                if info.get("streaming_availability"):
                    movie.streaming_availability = sorted(
                        set(movie.streaming_availability + list(info["streaming_availability"]))
                    )

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
                if info.get("streaming_availability"):
                    movie.streaming_availability = sorted(
                        set(movie.streaming_availability + list(info["streaming_availability"]))
                    )

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
        timeout_seconds: float = 3.0,
    ) -> tuple[str, SourcePayload, AgentResult]:
        # Phase 2: Check agent cache first
        agent_name = agent.name
        if self._is_agent_cache_valid(agent_name):
            _, cached_payload = self._agent_cache[agent_name]
            logger.debug("Using cached results for agent %s", agent_name)
            notes = cached_payload.metadata.get("notes") if isinstance(cached_payload.metadata, dict) else None
            return (
                agent_name,
                cached_payload,
                AgentResult(
                    agent=agent_name,
                    status="cached",
                    runtime_ms=0,
                    item_count=len(cached_payload.movies),
                    goal=self._agent_goal(agent_name, getattr(agent, "goal", None)),
                    notes=f"(cached) {notes}" if notes else "(cached)",
                ),
            )

        # Cache miss - run the agent
        started = time.perf_counter()
        try:
            payload = await asyncio.wait_for(agent.collect(context), timeout=timeout_seconds)
            runtime_ms = int((time.perf_counter() - started) * 1000)
            notes = payload.metadata.get("notes") if isinstance(payload.metadata, dict) else None
            lowered_notes = (notes or "").lower()
            status = "success"
            if payload.movies == [] and any(
                marker in lowered_notes for marker in ["missing", "skip", "no "]
            ):
                status = "skipped"

            # Cache successful results
            if status == "success" and payload.movies:
                self._agent_cache[agent_name] = (time.time(), payload)
                ttl = self._get_agent_cache_ttl(agent_name)
                logger.debug("Cached %d movies from %s (TTL: %ds)", len(payload.movies), agent_name, ttl)

            return (
                agent_name,
                payload,
                AgentResult(
                    agent=agent_name,
                    status=status,
                    runtime_ms=runtime_ms,
                    item_count=len(payload.movies),
                    goal=self._agent_goal(agent_name, getattr(agent, "goal", None)),
                    notes=notes,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            runtime_ms = int((time.perf_counter() - started) * 1000)
            return (
                agent_name,
                SourcePayload(),
                AgentResult(
                    agent=agent_name,
                    status="error",
                    runtime_ms=runtime_ms,
                    item_count=0,
                    goal=self._agent_goal(agent_name, getattr(agent, "goal", None)),
                    notes=str(exc),
                ),
            )

    @staticmethod
    def _normalize_movie(movie: MovieCandidate) -> None:
        title = " ".join(str(movie.title or "").replace("’", "'").split()).strip()
        if title:
            movie.title = title
            movie.normalized_title = re.sub(r"[^a-z0-9]+", "", title.lower())
        if movie.year is None and movie.release_date and len(str(movie.release_date)) >= 4:
            try:
                movie.year = int(str(movie.release_date)[:4])
            except Exception:
                pass
        movie.evidence = [line for line in dict.fromkeys((movie.evidence or [])) if str(line).strip()]

    @staticmethod
    def _agent_goal(agent_name: str, explicit_goal: str | None = None) -> str:
        if explicit_goal:
            return explicit_goal

        goals = {
            "oscars": "Prioritize Oscar winners and nominees with actionable metadata and availability context.",
            "criterion": "Bring in curated Criterion films with clean identifiers and rich context.",
            "upcoming": "Surface near-term releases with reliable dates and card-ready metadata.",
            "releases": "Track release-calendar signals and concrete release timing.",
            "rottentomatoes": "Contribute critic consensus and score-based confidence signals.",
            "rogerebert": "Contribute critic-review depth and review-sourced quality signals.",
            "plex": "Mark what is immediately watchable in the local Plex library.",
            "radarr": "Mark what is already tracked in Radarr for quick action.",
            "usenet": "Surface downloadable titles with high-confidence release parsing.",
            "nzbgeek": "Surface downloadable titles with high-confidence release parsing.",
            "drunkenslug": "Surface downloadable titles with high-confidence release parsing.",
            "preference": "Inject user taste-memory priors into the swarm.",
        }
        return goals.get(
            agent_name.lower(),
            f"Gather high-signal movie candidates from {agent_name} with evidence the swarm can rank.",
        )

    async def _annotate_agent_reasoning(
        self,
        completed: list[tuple[str, SourcePayload, AgentResult]],
    ) -> None:
        for agent_name, payload, status in completed:
            notes = status.notes or payload.metadata.get("notes") if isinstance(payload.metadata, dict) else status.notes
            summary = notes or "Completed without explicit notes."
            status.reasoning = (
                f"{status.goal} Result: {status.item_count} items ({status.status}). {summary}"
            )

        if not self._llm_client:
            return

        prompt_rows: list[str] = []
        for idx, (agent_name, payload, status) in enumerate(completed):
            sample_titles = ", ".join(movie.title for movie in payload.movies[:3]) or "none"
            prompt_rows.append(
                (
                    f"{idx}. agent={agent_name}; status={status.status}; count={status.item_count}; "
                    f"goal={status.goal}; notes={status.notes or 'none'}; samples={sample_titles}"
                )
            )

        prompt = (
            "You are a swarm orchestrator. For each agent row, write one concise reasoning sentence "
            "(max 20 words) describing why its output matters now.\n"
            "Return strict JSON array with objects: "
            '[{"agent":"name","reasoning":"..."}].\n'
            "Rows:\n"
            + "\n".join(prompt_rows)
        )

        try:
            response = await self._llm_client.generate(
                prompt=prompt,
                system=(
                    "You produce strict JSON only. Keep reasoning practical, no fluff."
                ),
            )
        except Exception:
            return

        parsed = self._parse_json_array(response)
        if not parsed:
            return

        reasoning_by_agent: dict[str, str] = {}
        for item in parsed:
            if not isinstance(item, dict):
                continue
            name = str(item.get("agent") or "").strip()
            reasoning = str(item.get("reasoning") or "").strip()
            if name and reasoning:
                reasoning_by_agent[name] = reasoning

        for _, _, status in completed:
            if status.agent in reasoning_by_agent:
                status.reasoning = reasoning_by_agent[status.agent]

    @staticmethod
    def _parse_json_array(raw: str) -> list:
        text = (raw or "").strip()
        if not text:
            return []
        for candidate in (text, SwarmOrchestrator._extract_bracketed_json(text)):
            if not candidate:
                continue
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                continue
        return []

    @staticmethod
    def _extract_bracketed_json(text: str) -> str | None:
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return None
        return text[start:end + 1]

    @staticmethod
    def _apply_local_streaming_markers(source_movies: dict[str, list[MovieCandidate]]) -> None:
        for movies in source_movies.values():
            for movie in movies:
                providers = list(movie.streaming_availability or [])
                if movie.available_on_plex and "Plex" not in providers:
                    providers.append("Plex")
                if movie.available_on_radarr and "Radarr" not in providers:
                    providers.append("Radarr")
                if movie.available_on_usenet and "Usenet" not in providers:
                    providers.append("Usenet")
                movie.streaming_availability = providers

    async def _enrich_streaming_availability(self, recommendations: list, max_items: int = 40) -> None:
        for rec in recommendations:
            movie = rec.movie
            providers = list(movie.streaming_availability or [])
            if movie.available_on_plex and "Plex" not in providers:
                providers.append("Plex")
            if movie.available_on_radarr and "Radarr" not in providers:
                providers.append("Radarr")
            if movie.available_on_usenet and "Usenet" not in providers:
                providers.append("Usenet")
            movie.streaming_availability = providers

        if not self._tmdb_client:
            return

        semaphore = asyncio.Semaphore(6)

        async def enrich(movie: MovieCandidate) -> None:
            async with semaphore:
                try:
                    search_rows = await self._tmdb_client.search_movie(movie.title, movie.year)
                except Exception:
                    return
                if not search_rows:
                    return
                tmdb_id = search_rows[0].get("id")
                if not isinstance(tmdb_id, int):
                    return
                try:
                    providers = await self._tmdb_client.movie_watch_providers(tmdb_id, region="US")
                except Exception:
                    return
                if not providers:
                    return
                movie.streaming_availability = sorted(
                    set(movie.streaming_availability + providers)
                )

        await asyncio.gather(*(enrich(rec.movie) for rec in recommendations[:max_items]))

    async def _augment_card_evidence_with_llm(self, recommendations: list, max_items: int = 30) -> None:
        if not recommendations:
            return

        if not self._llm_client:
            # No LLM available - skip adding redundant swarm insights
            return

        rows: list[str] = []
        for idx, rec in enumerate(recommendations[:max_items]):
            movie = rec.movie
            rows.append(
                (
                    f"{idx}. {movie.title} ({movie.year or 'n/a'}) | "
                    f"sources={','.join(movie.source_tags[:6])} | "
                    f"awards={','.join(movie.award_labels[:3]) or 'none'} | "
                    f"streaming={','.join(movie.streaming_availability[:4]) or 'unknown'} | "
                    f"reasons={','.join(reason.label for reason in rec.reasons[:4])}"
                )
            )

        prompt = (
            "Generate concise swarm-card insights for each movie.\n"
            "Return strict JSON array with objects: "
            '[{"index":0,"insight":"..."}].\n'
            "Rules: insight <= 18 words, factual, actionable, no hype.\n"
            "Movies:\n"
            + "\n".join(rows)
        )

        try:
            response = await self._llm_client.generate(
                prompt=prompt,
                system="You are a pragmatic movie recommendation analyst. Return JSON only.",
            )
            parsed = self._parse_json_array(response)
        except Exception:
            parsed = []

        insights_by_index: dict[int, str] = {}
        for item in parsed:
            if not isinstance(item, dict):
                continue
            raw_index = item.get("index")
            insight = str(item.get("insight") or "").strip()
            if not insight:
                continue
            try:
                idx = int(raw_index)
            except Exception:
                continue
            if 0 <= idx < len(recommendations[:max_items]):
                insights_by_index[idx] = insight

        for idx, rec in enumerate(recommendations):
            insight = insights_by_index.get(idx) if idx < max_items else None
            if insight:
                rec.movie.swarm_insight = insight

    @staticmethod
    def _deterministic_swarm_insight(movie: MovieCandidate) -> str:
        sources = ", ".join(movie.source_tags[:3]) if movie.source_tags else "multiple signals"
        if movie.streaming_availability:
            return (
                f"Backed by {sources}; currently actionable via "
                f"{', '.join(movie.streaming_availability[:2])}."
            )
        if movie.best_picture or movie.best_actor:
            return f"Backed by {sources} and awards credibility; strong candidate for immediate watchlist consideration."
        return f"Backed by {sources}; prioritized by swarm evidence overlap."

    @staticmethod
    def _append_evidence(movie: MovieCandidate, line: str) -> None:
        clean = " ".join(str(line or "").split()).strip()
        if not clean:
            return
        current = [str(item).strip() for item in (movie.evidence or []) if str(item).strip()]
        if clean not in current:
            current.append(clean)
        movie.evidence = current

    async def _generate_personalized_explanations(
        self,
        recommendations: list,
        user_id: str,
        max_items: int = 20,
    ) -> None:
        """Generate personalized explanations for why each movie is recommended."""
        if not recommendations:
            return

        # Build user preferences from feedback history
        user_prefs = UserPreferences()
        if self._memory_store:
            try:
                feedback_rows = self._memory_store.recent_feedback(user_id=user_id, limit=50)
                if feedback_rows:
                    rows_as_dicts = [
                        {
                            "title": row.title,
                            "liked": row.liked,
                            "genres_json": json.dumps(row.genres),
                            "year": row.year,
                        }
                        for row in feedback_rows
                    ]
                    user_prefs = build_user_preferences(rows_as_dicts)
            except Exception:
                pass

        # Create a temporary SwarmContext for explanation generation
        context = SwarmContext(
            user_id=user_id,
            requested_count=len(recommendations),
            now_iso=datetime.now(UTC).isoformat(),
            llm_client=self._llm_client,
            user_preferences=user_prefs,
        )

        semaphore = asyncio.Semaphore(5)  # Limit concurrent LLM calls

        def _explanation_cache_key(movie) -> str:
            """Generate cache key for explanation memoization."""
            genres_str = ",".join(sorted(movie.genres or []))
            return f"{movie.title}:{movie.year or 'na'}:{genres_str}"

        async def explain(rec) -> None:
            async with semaphore:
                movie = rec.movie

                # Phase 5: Check explanation cache first
                cache_key = _explanation_cache_key(movie)
                if cache_key in self._explanation_cache:
                    rec.explanation = self._explanation_cache[cache_key]
                    return

                # Cache miss - generate explanation
                explanation = await context.explain_recommendation(
                    title=movie.title,
                    year=movie.year,
                    genres=movie.genres,
                    sources=movie.source_tags,
                    evidence=movie.evidence,
                    rt_score=movie.rottentomatoes_score,
                )
                rec.explanation = explanation

                # Cache the explanation
                if explanation:
                    self._explanation_cache[cache_key] = explanation

        await asyncio.gather(*(explain(rec) for rec in recommendations[:max_items]))

        # Fill remaining with factual explanations
        for rec in recommendations[max_items:]:
            rec.explanation = context._factual_explanation(
                rec.movie.source_tags,
                rec.movie.genres,
                rec.movie.rottentomatoes_score,
            )

    async def _calibrate_front_scores_with_llm(self, recommendations: list, max_items: int = 30) -> None:
        if not recommendations:
            return

        deterministic_scores: dict[int, float] = {}
        for idx, rec in enumerate(recommendations):
            score = self._deterministic_front_score(rec)
            deterministic_scores[idx] = score
            rec.score = round(score, 2)

        if not self._llm_client:
            return

        rows: list[str] = []
        for idx, rec in enumerate(recommendations[:max_items]):
            movie = rec.movie
            critic = self._critic_anchor_score(movie)
            rows.append(
                (
                    f"{idx}. {movie.title} ({movie.year or 'n/a'}) | "
                    f"base={deterministic_scores[idx]:.1f} | "
                    f"critic={critic if critic is not None else 'na'} | "
                    f"sources={','.join(movie.source_tags[:6])} | "
                    f"reasons={','.join(reason.label for reason in rec.reasons[:5])}"
                )
            )

        prompt = (
            "Calibrate FRONT display scores for movies.\n"
            "Goal: avoid lowballing high-critic movies while staying realistic.\n"
            "Return strict JSON array only: [{\"index\":0,\"score\":88,\"why\":\"short reason\"}].\n"
            "Rules:\n"
            "- score integer 1-99\n"
            "- trust critic signals (Rotten Tomatoes / RogerEbert) when present\n"
            "- keep one short factual reason in 'why'\n"
            "Movies:\n"
            + "\n".join(rows)
        )

        try:
            response = await self._llm_client.generate(
                prompt=prompt,
                system="You are a pragmatic movie scoring assistant. JSON only.",
            )
            parsed = self._parse_json_array(response)
        except Exception:
            parsed = []

        if not parsed:
            return

        for item in parsed:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("index"))
                proposed = float(item.get("score"))
            except Exception:
                continue
            if idx < 0 or idx >= min(len(recommendations), max_items):
                continue

            rec = recommendations[idx]
            anchor = self._critic_anchor_score(rec.movie)
            deterministic = deterministic_scores.get(idx, rec.score)

            bounded = max(1.0, min(99.0, proposed))
            if anchor is not None:
                bounded = max(bounded, anchor - 6.0)
                bounded = min(bounded, anchor + 12.0)

            # Keep the calibrated score from dropping too far below deterministic baseline.
            bounded = max(bounded, deterministic - 4.0)

            rec.score = round(bounded, 2)
            why = str(item.get("why") or "").strip()
            if why:
                self._append_evidence(rec.movie, f"Score calibration: {why}")

    @staticmethod
    def _critic_anchor_score(movie: MovieCandidate) -> float | None:
        if movie.rottentomatoes_score is not None:
            return float(max(0, min(movie.rottentomatoes_score, 100)))
        if movie.rogerebert_score is not None:
            score = float(movie.rogerebert_score)
            if score <= 4.0:
                return max(0.0, min((score / 4.0) * 100.0, 100.0))
            if score <= 5.0:
                return max(0.0, min((score / 5.0) * 100.0, 100.0))
            return max(0.0, min(score, 100.0))
        return None

    def _deterministic_front_score(self, rec) -> float:  # noqa: ANN001
        movie = rec.movie
        base = float(max(1.0, min(rec.score, 99.0)))
        critic = self._critic_anchor_score(movie)
        tags = {str(tag).lower() for tag in (movie.source_tags or [])}
        source_span = min(len(tags), 5)
        reason_values = {
            str(reason.label or "").lower(): float(reason.value or 0.0)
            for reason in (rec.reasons or [])
        }

        availability_bonus = 0.0
        if movie.available_on_plex or movie.available_on_radarr or movie.available_on_usenet:
            availability_bonus = 4.0

        if critic is not None:
            blended = (critic * 0.84) + (base * 0.16) + (source_span * 0.8) + availability_bonus
            floor = critic - 5.0
            return max(1.0, min(99.0, max(blended, floor)))

        # No critic score available: derive a practical confidence score from swarm signals.
        score = max(base, 38.0)

        if "releases" in tags:
            score = max(score, 54.0)
        if "upcoming" in tags or bool(movie.release_date):
            score = max(score, 56.0)

        days_until_release = self._days_until_release(movie.release_date)
        if days_until_release is not None:
            if days_until_release >= 0:
                # Near-term releases should score higher confidence than distant ones.
                proximity_boost = max(0.0, 10.0 - (days_until_release / 18.0))
                score += proximity_boost
            else:
                score += 2.0

        score += min(source_span * 1.8, 8.0)
        if movie.best_picture:
            score = max(score, 70.0)
        if movie.best_actor:
            score = max(score, 66.0)
        if movie.streaming_availability:
            score += min(len(movie.streaming_availability) * 2.0, 8.0)
        if movie.poster_url:
            score += 1.0
        if movie.overview:
            score += 1.0

        score += min(reason_values.get("upcoming", 0.0) * 14.0, 10.0)
        score += min(reason_values.get("releases.com", 0.0) * 12.0, 8.0)
        score += min(reason_values.get("availability", 0.0) * 8.0, 6.0)

        return max(1.0, min(99.0, score))

    @staticmethod
    def _days_until_release(raw_date: str | None) -> int | None:
        if not raw_date:
            return None
        try:
            release = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00")).date()
        except Exception:
            return None
        return (release - datetime.now(UTC).date()).days
