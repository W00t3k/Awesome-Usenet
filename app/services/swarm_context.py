"""
SwarmContext - LLM-enabled context for intelligent agent decision-making.

This module provides agents with access to:
- User preference data (liked genres, decades, titles)
- LLM-powered query generation
- Agent collaboration via shared discovery cache
- Smart filtering and ranking capabilities
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any

from app.clients.llm_client import UnifiedLLMClient

logger = logging.getLogger(__name__)


@dataclass
class UserPreferences:
    """Aggregated user preferences from feedback history."""
    liked_titles: list[str] = field(default_factory=list)
    liked_genres: list[str] = field(default_factory=list)
    preferred_decades: list[str] = field(default_factory=list)
    disliked_genres: list[str] = field(default_factory=list)
    average_liked_year: int | None = None


@dataclass
class SwarmContext:
    """
    Context object passed to agents for intelligent decision-making.

    Provides LLM access, user preferences, and agent collaboration capabilities.
    Agents can use this to generate smarter search queries and filter results.
    """
    user_id: str
    requested_count: int
    now_iso: str

    # LLM interface (Groq Cloud preferred, Ollama fallback)
    llm_client: UnifiedLLMClient | None = None

    # User preference data from feedback history
    user_preferences: UserPreferences = field(default_factory=UserPreferences)

    # Shared discovery cache for agent collaboration
    discovery_cache: dict[str, Any] = field(default_factory=dict)

    # Track which agents have contributed
    contributing_agents: list[str] = field(default_factory=list)

    async def generate_search_queries(
        self,
        agent_name: str,
        source_type: str,
        base_queries: list[str] | None = None,
    ) -> list[str]:
        """
        Use LLM to generate targeted search queries based on user preferences.

        Args:
            agent_name: Name of the calling agent
            source_type: Type of source being searched (e.g., "usenet", "tmdb", "rogerebert")
            base_queries: Optional base queries to enhance

        Returns:
            List of search query strings (max 5)
        """
        if not self.llm_client:
            return base_queries or []

        # Build preference context
        pref_context = []
        if self.user_preferences.liked_genres:
            pref_context.append(f"Liked genres: {', '.join(self.user_preferences.liked_genres[:5])}")
        if self.user_preferences.preferred_decades:
            pref_context.append(f"Preferred eras: {', '.join(self.user_preferences.preferred_decades[:3])}")
        if self.user_preferences.liked_titles:
            pref_context.append(f"Recently liked: {', '.join(self.user_preferences.liked_titles[:3])}")

        if not pref_context:
            return base_queries or []

        prompt = f"""Generate 5 targeted search queries for finding movies.
User preferences:
{chr(10).join(pref_context)}

Source being searched: {source_type}
Agent: {agent_name}

Generate diverse search queries that would find movies matching these preferences.
Return ONLY a JSON array of strings, no explanation: ["query1", "query2", ...]"""

        try:
            response = await self.llm_client.generate(prompt)
            # Parse JSON array from response
            match = re.search(r'\[.*?\]', response, re.DOTALL)
            if match:
                queries = json.loads(match.group())
                if isinstance(queries, list):
                    return [str(q) for q in queries[:5]]
        except Exception as e:
            logger.debug(f"LLM query generation failed: {e}")

        return base_queries or []

    async def rank_candidates(
        self,
        movies: list[dict],
        criteria: str = "relevance to user preferences",
        max_items: int = 20,
    ) -> list[dict]:
        """
        Use LLM to rank movie candidates by relevance.

        Args:
            movies: List of movie dicts with at least 'title' and optional 'year', 'genres'
            criteria: What to optimize for
            max_items: Maximum items to rank

        Returns:
            Reordered list with top items first
        """
        if not self.llm_client or len(movies) <= 1:
            return movies

        # Limit to max_items
        subset = movies[:max_items]

        # Build preference summary
        pref_summary = []
        if self.user_preferences.liked_genres:
            pref_summary.append(f"Likes: {', '.join(self.user_preferences.liked_genres[:3])}")
        if self.user_preferences.disliked_genres:
            pref_summary.append(f"Avoids: {', '.join(self.user_preferences.disliked_genres[:3])}")

        # Build movie list
        movie_lines = []
        for i, m in enumerate(subset):
            title = m.get("title", "Unknown")
            year = m.get("year", "")
            genres = m.get("genres", [])
            genre_str = ", ".join(genres[:3]) if genres else ""
            movie_lines.append(f"{i}: {title} ({year}) [{genre_str}]")

        prompt = f"""Rank these movies by {criteria}.
User preferences: {' | '.join(pref_summary) or 'Unknown'}

Movies:
{chr(10).join(movie_lines)}

Return ONLY a JSON array of indices in order of relevance (best first): [0, 3, 1, ...]"""

        try:
            response = await self.llm_client.generate(prompt)
            match = re.search(r'\[[\d,\s]+\]', response)
            if match:
                indices = json.loads(match.group())
                if isinstance(indices, list):
                    # Reorder based on indices
                    reordered = []
                    seen = set()
                    for idx in indices:
                        if isinstance(idx, int) and 0 <= idx < len(subset) and idx not in seen:
                            reordered.append(subset[idx])
                            seen.add(idx)
                    # Add any remaining items
                    for i, m in enumerate(subset):
                        if i not in seen:
                            reordered.append(m)
                    # Append items beyond max_items
                    reordered.extend(movies[max_items:])
                    return reordered
        except Exception as e:
            logger.debug(f"LLM ranking failed: {e}")

        return movies

    async def should_include_movie(
        self,
        title: str,
        year: int | None,
        evidence: str,
    ) -> tuple[bool, str]:
        """
        Let LLM decide if an unusual movie is worth including based on context.

        Args:
            title: Movie title
            year: Release year (optional)
            evidence: Why this movie was found (e.g., "Unusual release pattern")

        Returns:
            Tuple of (should_include: bool, reason: str)
        """
        if not self.llm_client:
            return True, "No LLM available, including by default"

        # Build preference context
        pref_parts = []
        if self.user_preferences.liked_genres:
            pref_parts.append(f"Liked genres: {', '.join(self.user_preferences.liked_genres[:3])}")
        if self.user_preferences.liked_titles:
            pref_parts.append(f"Recently liked: {', '.join(self.user_preferences.liked_titles[:2])}")

        prompt = f"""Should this movie be included in recommendations?

Movie: {title} ({year or 'Unknown year'})
Context: {evidence}
User preferences: {' | '.join(pref_parts) or 'Unknown'}

Reply with ONLY "YES" or "NO" followed by a brief reason (max 10 words)."""

        try:
            response = await self.llm_client.generate(prompt)
            response_upper = response.strip().upper()
            if response_upper.startswith("YES"):
                reason = response.split("YES", 1)[-1].strip().lstrip(":").strip()[:50]
                return True, reason or "LLM approved"
            elif response_upper.startswith("NO"):
                reason = response.split("NO", 1)[-1].strip().lstrip(":").strip()[:50]
                return False, reason or "LLM filtered"
        except Exception as e:
            logger.debug(f"LLM inclusion check failed: {e}")

        return True, "LLM check failed, including by default"

    async def collaborate(
        self,
        agent_name: str,
        message: str,
        data: dict[str, Any],
    ) -> None:
        """
        Allow agents to share discoveries with each other.

        Args:
            agent_name: Name of the contributing agent
            message: Human-readable description of what was found
            data: Structured data to share (e.g., titles, themes, trends)
        """
        self.discovery_cache[agent_name] = {
            "message": message,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if agent_name not in self.contributing_agents:
            self.contributing_agents.append(agent_name)
        logger.debug(f"Agent '{agent_name}' shared: {message}")

    def get_collaborative_context(self) -> str:
        """
        Get a summary of what other agents have discovered.

        Returns:
            Human-readable summary of shared discoveries
        """
        if not self.discovery_cache:
            return "No collaborative context yet"

        lines = []
        for agent, info in self.discovery_cache.items():
            lines.append(f"- {agent}: {info.get('message', 'No message')}")
        return "\n".join(lines)

    def get_trending_themes(self) -> list[str]:
        """
        Extract trending themes from collaborative discoveries.

        Returns:
            List of theme strings mentioned by multiple agents
        """
        themes: dict[str, int] = {}
        for agent, info in self.discovery_cache.items():
            data = info.get("data", {})
            for theme in data.get("themes", []):
                themes[theme] = themes.get(theme, 0) + 1

        # Return themes mentioned by 2+ agents
        return [theme for theme, count in themes.items() if count >= 2]

    async def explain_recommendation(
        self,
        title: str,
        year: int | None,
        genres: list[str],
        sources: list[str],
        evidence: list[str],
        rt_score: int | None = None,
    ) -> str:
        """
        Generate intelligent explanation using LLM + factual data.
        Always tries LLM first for personalized insights.
        """
        # Always try LLM for intelligent explanations
        if self.llm_client:
            llm_result = await self._llm_explanation(
                title, year, genres, sources, evidence, rt_score
            )
            if llm_result:
                return llm_result

        # Fallback to factual
        return self._factual_explanation(sources, genres, rt_score)

    async def _llm_explanation(
        self,
        title: str,
        year: int | None,
        genres: list[str],
        sources: list[str],
        evidence: list[str],
        rt_score: int | None = None,
    ) -> str:
        """Generate LLM-powered explanation combining facts + user preferences."""
        # Build context
        facts = []
        if rt_score and rt_score > 0:
            facts.append(f"RT score: {rt_score}%")

        sources_lower = {s.lower() for s in sources}
        if "best-picture-winner" in sources_lower:
            facts.append("Best Picture winner")
        if "cannes" in sources_lower:
            facts.append("Cannes winner")
        if "criterion" in sources_lower:
            facts.append("Criterion Collection")
        if "a24" in sources_lower:
            facts.append("A24 film")

        user_prefs = []
        if self.user_preferences.liked_genres:
            user_prefs.append(f"likes {', '.join(self.user_preferences.liked_genres[:2])}")
        if self.user_preferences.liked_titles:
            user_prefs.append(f"enjoyed {self.user_preferences.liked_titles[0]}")

        prompt = f"""Movie: "{title}" ({year or '?'}) - {', '.join(genres[:2]) if genres else 'unknown genre'}
Facts: {', '.join(facts) if facts else 'none'}
User: {', '.join(user_prefs) if user_prefs else 'new user'}

Write a 6-10 word insight about WHY this specific movie. Not generic praise.
Examples of good responses:
- "Tense Korean thriller with shocking class commentary"
- "Visual masterpiece from acclaimed director"
- "Dark comedy matching your taste for satire"
- "Fresh horror with 94% RT buzz"

Your response (one line only):"""

        try:
            response = await self.llm_client.generate(prompt)
            explanation = response.strip().split('\n')[0].strip()
            explanation = explanation.strip('"\'.-')
            # Capitalize first letter
            if explanation:
                explanation = explanation[0].upper() + explanation[1:]
            if len(explanation) > 70:
                explanation = explanation[:67] + "..."
            if explanation and len(explanation) > 10:
                return explanation
        except Exception as e:
            logger.debug(f"LLM explanation failed: {e}")

        return ""

    def _factual_explanation(
        self,
        sources: list[str],
        genres: list[str],
        rt_score: int | None = None,
    ) -> str:
        """Generate factual explanation from source data only."""
        sources_lower = {s.lower() for s in sources}

        facts: list[str] = []

        # RT score (high priority - always show if available)
        if rt_score is not None and rt_score > 0:
            facts.append(f"RT {rt_score}%")

        # Awards
        if "best-picture-winner" in sources_lower:
            facts.append("Best Picture winner")
        elif "best-picture-nominee" in sources_lower:
            facts.append("Oscar nominated")
        elif "oscars" in sources_lower:
            facts.append("Oscar recognized")
        if "cannes" in sources_lower:
            facts.append("Cannes")
        if "bafta" in sources_lower:
            facts.append("BAFTA")
        if "golden_globes" in sources_lower:
            facts.append("Golden Globe")
        if "sundance" in sources_lower:
            facts.append("Sundance")

        # Curated lists
        if "criterion" in sources_lower or "criterion-release" in sources_lower:
            facts.append("Criterion Collection")
        if "sight_sound" in sources_lower:
            facts.append("Sight & Sound Top 100")
        if "afi100" in sources_lower:
            facts.append("AFI 100")
        if "imdb_top250" in sources_lower:
            facts.append("IMDb Top 250")
        if "letterboxd" in sources_lower:
            facts.append("Letterboxd Top")
        if "metacritic" in sources_lower:
            facts.append("Metacritic 90+")

        # Studios
        if "a24" in sources_lower:
            facts.append("A24")
        if "neon" in sources_lower:
            facts.append("NEON")
        if "ghibli" in sources_lower:
            facts.append("Studio Ghibli")
        if "pixar" in sources_lower:
            facts.append("Pixar")
        if "disney" in sources_lower:
            facts.append("Disney")
        if "blumhouse" in sources_lower:
            facts.append("Blumhouse")

        # Genre collections
        if "horror_classics" in sources_lower:
            facts.append("Horror classic")
        if "scifi" in sources_lower:
            facts.append("Sci-fi essential")
        if "film_noir" in sources_lower:
            facts.append("Film noir")
        if "korean_cinema" in sources_lower:
            facts.append("Korean cinema")
        if "anime" in sources_lower:
            facts.append("Anime essential")
        if "hidden_gems" in sources_lower:
            facts.append("Hidden gem")
        if "directors" in sources_lower:
            facts.append("Director spotlight")
        if "film_registry" in sources_lower:
            facts.append("National Film Registry")
        if "boxoffice" in sources_lower:
            facts.append("Box office hit")

        # Availability/status (separate from prestige facts)
        is_available = "nzbgeek" in sources_lower or "usenet" in sources_lower or "drunkenslug" in sources_lower
        is_now_playing = "now-playing" in sources_lower
        is_upcoming = "upcoming" in sources_lower

        # Build explanation: prestige facts first, then availability
        if facts:
            # Show up to 4 prestige facts
            explanation = " · ".join(facts[:4])
            # Append availability at the end
            if is_available:
                explanation += " — Available"
            elif is_now_playing:
                explanation += " — In theaters"
            return explanation

        # No prestige facts - show availability as main info
        if is_available:
            if genres:
                return f"{genres[0]} — Available now"
            return "Available now"
        if is_now_playing:
            if genres:
                return f"{genres[0]} — In theaters"
            return "In theaters"
        if is_upcoming:
            if genres:
                return f"Upcoming {genres[0].lower()}"
            return "Upcoming release"

        # Fallback: use source count or genre
        if len(sources) >= 2:
            return f"From {len(sources)} sources"
        if genres:
            return genres[0]
        return ""


def build_user_preferences(
    feedback_rows: list[dict],
    max_titles: int = 10,
    max_genres: int = 8,
) -> UserPreferences:
    """
    Build UserPreferences from feedback history.

    Args:
        feedback_rows: List of feedback dicts with 'title', 'liked', 'genres_json', 'year'
        max_titles: Maximum liked titles to include
        max_genres: Maximum genres to include

    Returns:
        UserPreferences instance
    """
    liked_titles: list[str] = []
    genre_counts: dict[str, int] = {}
    disliked_genres: dict[str, int] = {}
    years: list[int] = []
    decade_counts: dict[str, int] = {}

    for row in feedback_rows:
        title = row.get("title", "")
        liked = row.get("liked", False)
        genres_json = row.get("genres_json", "[]")
        year = row.get("year")

        # Parse genres
        try:
            genres = json.loads(genres_json) if genres_json else []
        except json.JSONDecodeError:
            genres = []

        if liked:
            if title and len(liked_titles) < max_titles:
                liked_titles.append(title)
            for genre in genres:
                genre_counts[genre] = genre_counts.get(genre, 0) + 1
            if isinstance(year, int) and 1900 <= year <= 2030:
                years.append(year)
                decade = f"{(year // 10) * 10}s"
                decade_counts[decade] = decade_counts.get(decade, 0) + 1
        else:
            for genre in genres:
                disliked_genres[genre] = disliked_genres.get(genre, 0) + 1

    # Sort genres by frequency
    liked_genres = sorted(genre_counts.keys(), key=lambda g: genre_counts[g], reverse=True)[:max_genres]
    disliked = sorted(disliked_genres.keys(), key=lambda g: disliked_genres[g], reverse=True)[:5]
    preferred_decades = sorted(decade_counts.keys(), key=lambda d: decade_counts[d], reverse=True)[:3]

    avg_year = int(sum(years) / len(years)) if years else None

    return UserPreferences(
        liked_titles=liked_titles,
        liked_genres=liked_genres,
        preferred_decades=preferred_decades,
        disliked_genres=disliked,
        average_liked_year=avg_year,
    )
