"""Mood-based movie discovery engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

MoodType = Literal[
    "cozy",
    "thrilling",
    "mind-bending",
    "feel-good",
    "nostalgic",
    "dark",
    "romantic",
    "adventurous",
    "funny",
    "inspiring",
]


@dataclass
class MoodProfile:
    """Configuration for a mood category."""

    name: str
    display_name: str
    emoji: str
    description: str
    genres: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    exclude_genres: list[str] = field(default_factory=list)
    year_bias: str | None = None  # "classic", "modern", "recent", None
    min_rating: float = 0.0
    prefer_popular: bool = False
    prefer_obscure: bool = False


# Mood definitions
MOODS: dict[str, MoodProfile] = {
    "cozy": MoodProfile(
        name="cozy",
        display_name="Cozy Night In",
        emoji="🛋️",
        description="Warm, comforting films perfect for a relaxed evening",
        genres=["Comedy", "Romance", "Animation", "Family", "Drama"],
        keywords=["heartwarming", "gentle", "comfort", "wholesome", "charming"],
        exclude_genres=["Horror", "Thriller", "War"],
        prefer_popular=True,
    ),
    "thrilling": MoodProfile(
        name="thrilling",
        display_name="Edge of Seat",
        emoji="😱",
        description="Heart-pounding suspense and non-stop action",
        genres=["Thriller", "Action", "Horror", "Mystery", "Crime"],
        keywords=["suspense", "tension", "intense", "gripping", "explosive"],
        exclude_genres=["Romance", "Family", "Animation"],
        min_rating=6.5,
    ),
    "mind-bending": MoodProfile(
        name="mind-bending",
        display_name="Mind-Bending",
        emoji="🧠",
        description="Films that challenge your perception and make you think",
        genres=["Science Fiction", "Mystery", "Thriller", "Drama"],
        keywords=["twist", "cerebral", "complex", "philosophical", "surreal", "puzzle"],
        exclude_genres=["Family", "Animation", "Comedy"],
        min_rating=7.0,
    ),
    "feel-good": MoodProfile(
        name="feel-good",
        display_name="Feel Good",
        emoji="😊",
        description="Uplifting stories that leave you smiling",
        genres=["Comedy", "Romance", "Family", "Animation", "Musical"],
        keywords=["uplifting", "happy", "inspiring", "fun", "lighthearted", "joyful"],
        exclude_genres=["Horror", "Thriller", "War", "Crime"],
        prefer_popular=True,
    ),
    "nostalgic": MoodProfile(
        name="nostalgic",
        display_name="Nostalgic",
        emoji="📼",
        description="Classic films and retro vibes from decades past",
        genres=["Drama", "Comedy", "Adventure", "Romance", "Science Fiction"],
        keywords=["classic", "timeless", "vintage", "retro", "golden age"],
        year_bias="classic",
        min_rating=7.0,
    ),
    "dark": MoodProfile(
        name="dark",
        display_name="Dark & Gritty",
        emoji="🌑",
        description="Intense, mature themes and morally complex stories",
        genres=["Drama", "Crime", "Thriller", "Horror", "War"],
        keywords=["dark", "gritty", "noir", "bleak", "intense", "brutal"],
        exclude_genres=["Family", "Animation", "Comedy", "Musical"],
        min_rating=7.0,
    ),
    "romantic": MoodProfile(
        name="romantic",
        display_name="Romantic",
        emoji="💕",
        description="Love stories and romantic adventures",
        genres=["Romance", "Drama", "Comedy"],
        keywords=["love", "romantic", "passion", "relationship", "chemistry"],
        exclude_genres=["Horror", "War", "Crime"],
    ),
    "adventurous": MoodProfile(
        name="adventurous",
        display_name="Adventure",
        emoji="🗺️",
        description="Epic journeys and exciting explorations",
        genres=["Adventure", "Action", "Fantasy", "Science Fiction"],
        keywords=["epic", "journey", "quest", "exploration", "hero"],
        prefer_popular=True,
    ),
    "funny": MoodProfile(
        name="funny",
        display_name="Hilarious",
        emoji="😂",
        description="Laugh-out-loud comedies",
        genres=["Comedy"],
        keywords=["funny", "hilarious", "comedy", "satire", "parody", "witty"],
        exclude_genres=["Horror", "War", "Drama"],
    ),
    "inspiring": MoodProfile(
        name="inspiring",
        display_name="Inspiring",
        emoji="✨",
        description="True stories and tales of triumph",
        genres=["Drama", "Biography", "Documentary", "Sport"],
        keywords=["inspiring", "triumph", "overcome", "true story", "motivational"],
        min_rating=7.0,
    ),
}


def get_mood(mood_name: str) -> MoodProfile | None:
    """Get a mood profile by name."""
    return MOODS.get(mood_name.lower())


def get_all_moods() -> list[dict]:
    """Get all moods for frontend display."""
    return [
        {
            "name": mood.name,
            "display_name": mood.display_name,
            "emoji": mood.emoji,
            "description": mood.description,
        }
        for mood in MOODS.values()
    ]


def score_movie_for_mood(
    movie_genres: list[str],
    movie_keywords: list[str] | None,
    movie_year: int | None,
    movie_rating: float | None,
    mood: MoodProfile,
) -> float:
    """Score how well a movie matches a mood (0-100)."""
    score = 50.0  # Base score

    # Genre matching
    movie_genres_lower = [g.lower() for g in movie_genres]
    mood_genres_lower = [g.lower() for g in mood.genres]
    exclude_genres_lower = [g.lower() for g in mood.exclude_genres]

    genre_matches = sum(1 for g in movie_genres_lower if g in mood_genres_lower)
    if genre_matches > 0:
        score += min(genre_matches * 15, 30)

    # Excluded genre penalty
    excluded_matches = sum(1 for g in movie_genres_lower if g in exclude_genres_lower)
    if excluded_matches > 0:
        score -= excluded_matches * 20

    # Keyword matching (if provided)
    if movie_keywords:
        keywords_lower = [k.lower() for k in movie_keywords]
        keyword_matches = sum(
            1 for k in mood.keywords if any(k.lower() in kw for kw in keywords_lower)
        )
        score += min(keyword_matches * 10, 20)

    # Year bias
    if movie_year and mood.year_bias:
        if mood.year_bias == "classic" and movie_year < 1990:
            score += 15
        elif mood.year_bias == "classic" and movie_year < 1980:
            score += 20
        elif mood.year_bias == "modern" and movie_year >= 2010:
            score += 10
        elif mood.year_bias == "recent" and movie_year >= 2020:
            score += 15

    # Rating threshold
    if movie_rating and mood.min_rating > 0:
        if movie_rating >= mood.min_rating:
            score += 10
        else:
            score -= 15

    return max(0, min(100, score))


def filter_movies_by_mood(
    movies: list[dict],
    mood_name: str,
    min_score: float = 40.0,
) -> list[dict]:
    """Filter and sort movies by mood compatibility."""
    mood = get_mood(mood_name)
    if not mood:
        return movies

    scored_movies = []
    for movie in movies:
        mood_score = score_movie_for_mood(
            movie_genres=movie.get("genres", []),
            movie_keywords=movie.get("keywords"),
            movie_year=movie.get("year"),
            movie_rating=movie.get("vote_average") or movie.get("rating"),
            mood=mood,
        )

        if mood_score >= min_score:
            scored_movies.append({**movie, "mood_score": mood_score})

    # Sort by mood score descending
    scored_movies.sort(key=lambda m: m.get("mood_score", 0), reverse=True)
    return scored_movies


def infer_user_moods(feedback_history: list[dict]) -> list[dict]:
    """Analyze user's liked movies to suggest matching moods.

    Args:
        feedback_history: List of feedback records with 'liked', 'genres', 'title', etc.

    Returns:
        List of mood suggestions with scores, sorted by relevance.
    """
    if not feedback_history:
        return []

    # Count genre frequencies in liked movies
    genre_counts: dict[str, int] = {}
    liked_count = 0

    for feedback in feedback_history:
        if not feedback.get("liked"):
            continue
        liked_count += 1
        genres = feedback.get("genres") or []
        for genre in genres:
            genre_lower = genre.lower()
            genre_counts[genre_lower] = genre_counts.get(genre_lower, 0) + 1

    if liked_count == 0:
        return []

    # Score each mood based on genre overlap
    mood_scores: list[dict] = []

    for mood_name, mood_profile in MOODS.items():
        score = 0.0
        mood_genres_lower = [g.lower() for g in mood_profile.genres]
        exclude_genres_lower = [g.lower() for g in mood_profile.exclude_genres]

        # Add points for matching genres
        for genre, count in genre_counts.items():
            if genre in mood_genres_lower:
                score += count * 10
            if genre in exclude_genres_lower:
                score -= count * 5

        # Normalize by liked count
        if liked_count > 0:
            score = score / liked_count

        if score > 0:
            mood_scores.append({
                "name": mood_profile.name,
                "display_name": mood_profile.display_name,
                "emoji": mood_profile.emoji,
                "score": round(score, 1),
                "reason": f"Based on your {liked_count} liked movies",
            })

    # Sort by score descending and return top 3
    mood_scores.sort(key=lambda m: m["score"], reverse=True)
    return mood_scores[:3]


def get_mood_for_genres(genres: list[str]) -> str | None:
    """Suggest a single best mood based on genres.

    Args:
        genres: List of movie genres

    Returns:
        Best matching mood name, or None
    """
    if not genres:
        return None

    best_mood = None
    best_score = 0.0

    for mood_name, mood_profile in MOODS.items():
        mood_genres_lower = [g.lower() for g in mood_profile.genres]
        genres_lower = [g.lower() for g in genres]

        matches = sum(1 for g in genres_lower if g in mood_genres_lower)
        if matches > best_score:
            best_score = matches
            best_mood = mood_name

    return best_mood if best_score > 0 else None
