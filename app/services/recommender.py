from __future__ import annotations

from .models import Movie, Preferences
from .movie_catalog import MOVIES


def _normalized(values: tuple[str, ...] | set[str]) -> set[str]:
    return {value.lower() for value in values}


def _score_movie(movie: Movie, preferences: Preferences) -> float | None:
    if preferences.family_only and not movie.family_friendly:
        return None
    if (
        preferences.max_runtime_minutes is not None
        and movie.runtime_minutes > preferences.max_runtime_minutes
    ):
        return None

    score = 0.0

    movie_genres = _normalized(movie.genres)
    movie_moods = _normalized(movie.mood_tags)
    requested_genres = _normalized(preferences.genres)
    requested_moods = _normalized(preferences.moods)

    score += len(movie_genres & requested_genres) * 3
    score += len(movie_moods & requested_moods) * 2

    if preferences.min_year is not None:
        if movie.year >= preferences.min_year:
            score += 1.0
        else:
            score -= 1.0

    # Small tie-breaker toward shorter movies.
    score += max(0.0, 120.0 - movie.runtime_minutes) / 120.0
    return score


def recommend_movies(
    preferences: Preferences,
    *,
    limit: int = 5,
    catalog: tuple[Movie, ...] = MOVIES,
) -> list[Movie]:
    if limit < 1:
        return []

    scored_movies: list[tuple[float, Movie]] = []
    for movie in catalog:
        score = _score_movie(movie, preferences)
        if score is None:
            continue
        scored_movies.append((score, movie))

    scored_movies.sort(key=lambda pair: (pair[0], pair[1].year), reverse=True)
    return [movie for _, movie in scored_movies[:limit]]
