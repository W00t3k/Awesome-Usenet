"""LLM-powered explanation service for movie recommendations."""

from __future__ import annotations

import logging
from typing import Any

from app.clients.ollama_client import OllamaClient
from app.config import settings

logger = logging.getLogger(__name__)


class LLMExplainer:
    """Generate natural language explanations for movie recommendations."""

    def __init__(self, ollama_client: OllamaClient | None = None):
        self._client = ollama_client

    @property
    def client(self) -> OllamaClient | None:
        """Lazy-load Ollama client."""
        if self._client is None and settings.ollama_base_url:
            self._client = OllamaClient(
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
                timeout_seconds=30.0,
            )
        return self._client

    async def explain_recommendation(
        self,
        movie_title: str,
        movie_year: int | None,
        score: float,
        reasons: list[dict[str, Any]],
        genres: list[str] | None = None,
        overview: str | None = None,
    ) -> str:
        """Generate a natural language explanation for a recommendation.

        Args:
            movie_title: The movie title
            movie_year: Release year
            score: Recommendation score
            reasons: List of reason dicts with 'label', 'value', 'detail'
            genres: Optional list of genres
            overview: Optional movie overview

        Returns:
            Natural language explanation string
        """
        # Try LLM first if available
        if self.client:
            try:
                return await self._llm_explain(
                    movie_title, movie_year, score, reasons, genres, overview
                )
            except Exception as e:
                logger.warning(f"LLM explanation failed, using fallback: {e}")

        # Fallback to rule-based explanation
        return self._rule_based_explain(movie_title, movie_year, score, reasons, genres)

    async def _llm_explain(
        self,
        movie_title: str,
        movie_year: int | None,
        score: float,
        reasons: list[dict[str, Any]],
        genres: list[str] | None,
        overview: str | None,
    ) -> str:
        """Generate explanation using Ollama."""
        if not self.client:
            raise RuntimeError("Ollama client not available")

        # Format reasons for the prompt
        reasons_text = "\n".join(
            f"- {r['label']}: {r['detail']} (weight: {r['value']:.1f})"
            for r in reasons
        )

        year_text = f" ({movie_year})" if movie_year else ""
        genre_text = f"Genres: {', '.join(genres)}" if genres else ""
        overview_text = f"Plot: {overview[:200]}..." if overview else ""

        prompt = f"""You are explaining why a movie recommendation system suggested a specific film.
Write a brief, engaging 2-3 sentence explanation that sounds natural and conversational.

Movie: {movie_title}{year_text}
{genre_text}
{overview_text}
Overall Score: {score:.0f}/100

Recommendation factors:
{reasons_text}

Write a friendly explanation of why this movie was recommended. Focus on the most interesting reasons. Don't use bullet points."""

        response = await self.client.generate(
            prompt=prompt,
            system="You are a friendly movie expert. Keep responses concise and engaging.",
        )

        return response.strip() if response else self._rule_based_explain(
            movie_title, movie_year, score, reasons, genres
        )

    def _rule_based_explain(
        self,
        movie_title: str,
        movie_year: int | None,
        score: float,
        reasons: list[dict[str, Any]],
        genres: list[str] | None,
    ) -> str:
        """Generate a rule-based fallback explanation."""
        parts = []

        # Intro based on score
        year_text = f" ({movie_year})" if movie_year else ""
        if score >= 80:
            parts.append(f"'{movie_title}'{year_text} is a top pick for you!")
        elif score >= 60:
            parts.append(f"'{movie_title}'{year_text} could be a great match.")
        else:
            parts.append(f"'{movie_title}'{year_text} might interest you.")

        # Highlight top reasons
        top_reasons = sorted(reasons, key=lambda r: r.get("value", 0), reverse=True)[:2]

        reason_phrases = []
        for reason in top_reasons:
            label = reason.get("label", "").lower()
            detail = reason.get("detail", "")

            if "oscar" in label:
                reason_phrases.append("recognized at the Academy Awards")
            elif "criterion" in label:
                reason_phrases.append("part of the prestigious Criterion Collection")
            elif "preference" in label or "similar" in label:
                reason_phrases.append("similar to movies you've enjoyed")
            elif "rotten" in label or "rt" in label:
                reason_phrases.append("critically acclaimed")
            elif "ebert" in label:
                reason_phrases.append("praised by critics")
            elif "usenet" in label or "nzb" in label:
                reason_phrases.append("available now for download")
            elif "plex" in label:
                reason_phrases.append("already in your Plex library")
            elif detail:
                reason_phrases.append(detail.lower())

        if reason_phrases:
            parts.append(f"It's {' and '.join(reason_phrases)}.")

        # Add genre note if available
        if genres and len(genres) > 0:
            if len(genres) == 1:
                parts.append(f"A great {genres[0].lower()} film.")
            else:
                parts.append(f"This {genres[0].lower()}/{genres[1].lower()} blend might be just what you're looking for.")

        return " ".join(parts)


    async def generate_personalized_reason(
        self,
        movie_title: str,
        movie_year: int | None,
        movie_genres: list[str] | None,
        movie_overview: str | None,
        user_liked_genres: list[str] | None = None,
        user_liked_titles: list[str] | None = None,
    ) -> str:
        """Generate a personalized 'Why You'll Like This' explanation.

        Args:
            movie_title: The movie title
            movie_year: Release year
            movie_genres: Movie genres
            movie_overview: Movie plot overview
            user_liked_genres: Genres the user has liked
            user_liked_titles: Titles the user has liked

        Returns:
            Personalized explanation string
        """
        # Try LLM first if available
        if self.client:
            try:
                return await self._llm_personalized_reason(
                    movie_title, movie_year, movie_genres, movie_overview,
                    user_liked_genres, user_liked_titles
                )
            except Exception as e:
                logger.warning(f"LLM personalized reason failed, using fallback: {e}")

        # Fallback to rule-based
        return self._rule_based_personalized_reason(
            movie_title, movie_genres, user_liked_genres, user_liked_titles
        )

    async def _llm_personalized_reason(
        self,
        movie_title: str,
        movie_year: int | None,
        movie_genres: list[str] | None,
        movie_overview: str | None,
        user_liked_genres: list[str] | None,
        user_liked_titles: list[str] | None,
    ) -> str:
        """Generate personalized reason using Ollama."""
        if not self.client:
            raise RuntimeError("Ollama client not available")

        year_text = f" ({movie_year})" if movie_year else ""
        genre_text = f"Genres: {', '.join(movie_genres)}" if movie_genres else ""
        overview_text = f"Plot: {movie_overview[:150]}..." if movie_overview else ""

        liked_info = ""
        if user_liked_titles:
            liked_info += f"Movies they've enjoyed: {', '.join(user_liked_titles[:5])}\n"
        if user_liked_genres:
            liked_info += f"Favorite genres: {', '.join(user_liked_genres[:5])}"

        prompt = f"""Write ONE short, personalized sentence (15-25 words) explaining why someone would enjoy this movie.

Movie: {movie_title}{year_text}
{genre_text}
{overview_text}

User preferences:
{liked_info or "No preference data available"}

Write a friendly, personalized reason starting with "You'll love this because..." or similar. Be specific and engaging. ONE sentence only."""

        response = await self.client.generate(
            prompt=prompt,
            system="You are a friendly movie expert. Write only ONE concise sentence.",
        )

        result = response.strip() if response else ""
        # Ensure it's not too long
        if len(result) > 150:
            result = result[:147] + "..."
        return result or self._rule_based_personalized_reason(
            movie_title, movie_genres, user_liked_genres, user_liked_titles
        )

    def _rule_based_personalized_reason(
        self,
        movie_title: str,
        movie_genres: list[str] | None,
        user_liked_genres: list[str] | None,
        user_liked_titles: list[str] | None,
    ) -> str:
        """Generate rule-based personalized reason."""
        if not movie_genres:
            return f"A highly rated film worth checking out."

        primary_genre = movie_genres[0].lower() if movie_genres else "film"

        # Check for genre overlap with user preferences
        if user_liked_genres:
            user_genres_lower = [g.lower() for g in user_liked_genres]
            matching_genres = [g for g in movie_genres if g.lower() in user_genres_lower]
            if matching_genres:
                return f"Perfect for you \u2014 matches your love of {matching_genres[0].lower()} films."

        # Genre-specific reasons
        genre_reasons = {
            "action": "Packed with thrilling action sequences.",
            "comedy": "Great for when you need a good laugh.",
            "drama": "A compelling story with emotional depth.",
            "horror": "For those who enjoy a good scare.",
            "thriller": "Edge-of-your-seat suspense throughout.",
            "romance": "A heartwarming love story.",
            "sci-fi": "Imaginative sci-fi that expands the mind.",
            "science fiction": "Imaginative sci-fi that expands the mind.",
            "adventure": "An exciting journey you won't forget.",
            "animation": "Beautiful animation for all ages.",
            "documentary": "Eye-opening and thought-provoking.",
            "mystery": "A puzzle that keeps you guessing.",
            "fantasy": "A magical escape into another world.",
        }

        return genre_reasons.get(primary_genre, f"A standout {primary_genre} worth your time.")


# Singleton instance
_explainer: LLMExplainer | None = None


def get_explainer() -> LLMExplainer:
    """Get or create the singleton explainer instance."""
    global _explainer
    if _explainer is None:
        _explainer = LLMExplainer()
    return _explainer
