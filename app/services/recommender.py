from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import re

from app.models import MovieCandidate, Recommendation, RecommendationReason
from app.services.memory_store import MemoryStore

TV_EPISODE_PATTERN = re.compile(r"\bS\d{1,4}E\d{1,3}\b|\b\d{1,2}x\d{1,3}\b", re.I)


@dataclass
class ScoredMovie:
    movie: MovieCandidate
    score: float
    reasons: list[RecommendationReason]


class Recommender:
    def __init__(self, memory_store: MemoryStore):
        self._memory_store = memory_store

    async def rank(
        self,
        user_id: str,
        source_movies: dict[str, list[MovieCandidate]],
        top_n: int,
        sort_mode: str | None = None,
        required_sources: set[str] | None = None,
        release_date_from: date | None = None,
        release_date_to: date | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[Recommendation]:
        merged = self._merge_movies(source_movies)
        seen_keys = self._memory_store.seen_title_keys(user_id)
        scored: list[ScoredMovie] = []

        for key, movie in merged.items():
            if key in seen_keys:
                continue
            if required_sources and not self._movie_matches_sources(movie, required_sources):
                continue
            if not self._movie_matches_release_date(
                movie,
                release_date_from=release_date_from,
                release_date_to=release_date_to,
            ):
                continue
            if year_from is not None and (movie.year is None or movie.year < year_from):
                continue
            if year_to is not None and (movie.year is None or movie.year > year_to):
                continue
            score, reasons = await self._score_movie(user_id, movie)
            scored.append(ScoredMovie(movie=movie, score=score, reasons=reasons))

        scored = self._sort_scored_movies(scored, sort_mode)
        return [
            Recommendation(
                movie=item.movie,
                score=self._display_score(item.movie, item.score),
                reasons=item.reasons,
            )
            for item in scored[:top_n]
        ]

    @staticmethod
    def _release_sort_key(movie: MovieCandidate) -> tuple[int, int]:
        release = Recommender._coerce_release_date(movie.release_date)
        if release is not None:
            return (2, release.toordinal())
        if movie.year is not None and movie.year > 0:
            return (1, date(movie.year, 1, 1).toordinal())
        return (0, -1)

    @staticmethod
    def _sort_scored_movies(
        scored: list[ScoredMovie],
        sort_mode: str | None,
    ) -> list[ScoredMovie]:
        mode = (sort_mode or "score-desc").strip().lower()
        today = datetime.now(UTC).date()

        if mode == "year-desc":
            return sorted(scored, key=lambda item: (Recommender._release_sort_key(item.movie), item.score), reverse=True)

        if mode == "year-asc":
            return sorted(scored, key=lambda item: (Recommender._release_sort_key(item.movie), -item.score))

        if mode == "release-upcoming":
            upcoming = []
            for item in scored:
                release = Recommender._coerce_release_date(item.movie.release_date)
                if release is None or release < today:
                    continue
                upcoming.append((item, release))
            upcoming.sort(key=lambda pair: (pair[1], -pair[0].score))
            return [pair[0] for pair in upcoming]

        if mode == "release-current":
            released = []
            for item in scored:
                release = Recommender._coerce_release_date(item.movie.release_date)
                if release is None or release >= today:
                    continue
                released.append((item, release))
            released.sort(key=lambda pair: (pair[1], pair[0].score), reverse=True)
            return [pair[0] for pair in released]

        return sorted(scored, key=lambda item: item.score, reverse=True)

    @staticmethod
    def _score_to_hundred(raw_score: float) -> float:
        normalized = max(0.0, min(raw_score, 1.0))
        return round(normalized * 100.0, 2)

    @staticmethod
    def _display_score(movie: MovieCandidate, raw_score: float) -> float:
        computed = Recommender._score_to_hundred(raw_score)

        critic_hundred: float | None = None
        if movie.rottentomatoes_score is not None:
            critic_hundred = float(max(0, min(movie.rottentomatoes_score, 100)))
        elif movie.rogerebert_score is not None:
            score = float(movie.rogerebert_score)
            if score <= 4.0:
                critic_hundred = max(0.0, min((score / 4.0) * 100.0, 100.0))
            elif score <= 5.0:
                critic_hundred = max(0.0, min((score / 5.0) * 100.0, 100.0))
            else:
                critic_hundred = max(0.0, min(score, 100.0))

        if critic_hundred is not None:
            blended = (critic_hundred * 0.6) + (computed * 0.4)
            return round(blended, 2)

        return computed

    @staticmethod
    def _merge_movies(source_movies: dict[str, list[MovieCandidate]]) -> dict[str, MovieCandidate]:
        merged: dict[str, MovieCandidate] = {}
        for agent_name, movies in source_movies.items():
            for movie in movies:
                if movie.available_on_usenet and Recommender._looks_like_tv_episode(movie.title):
                    continue
                if agent_name not in movie.source_tags:
                    movie.source_tags = sorted(set(movie.source_tags + [agent_name]))
                key = Recommender._title_year_key(movie.title, movie.year)
                if key not in merged:
                    merged[key] = movie
                    continue

                existing = merged[key]
                existing.source_tags = sorted(set(existing.source_tags + movie.source_tags))
                existing.evidence = sorted(set(existing.evidence + movie.evidence))
                existing.available_on_plex = existing.available_on_plex or movie.available_on_plex
                existing.available_on_radarr = (
                    existing.available_on_radarr or movie.available_on_radarr
                )
                existing.available_on_usenet = (
                    existing.available_on_usenet or movie.available_on_usenet
                )
                if not existing.overview and movie.overview:
                    existing.overview = movie.overview
                if not existing.release_date and movie.release_date:
                    existing.release_date = movie.release_date
                if not existing.poster_url and movie.poster_url:
                    existing.poster_url = movie.poster_url
                if (
                    existing.rottentomatoes_score is None
                    and movie.rottentomatoes_score is not None
                ):
                    existing.rottentomatoes_score = movie.rottentomatoes_score
                if existing.rogerebert_score is None and movie.rogerebert_score is not None:
                    existing.rogerebert_score = movie.rogerebert_score
                if not existing.genres and movie.genres:
                    existing.genres = movie.genres

        return merged

    @staticmethod
    def _title_year_key(title: str, year: int | None) -> str:
        return f"{title.strip().lower()}::{year if year is not None else 'na'}"

    @staticmethod
    def _looks_like_tv_episode(title: str) -> bool:
        return bool(TV_EPISODE_PATTERN.search(title or ""))

    @staticmethod
    def _movie_matches_sources(movie: MovieCandidate, required_sources: set[str]) -> bool:
        tags = {tag.lower() for tag in movie.source_tags}

        if "rt" in required_sources and (
            "rottentomatoes" in tags or any(tag.startswith("rt-") for tag in tags)
        ):
            return True
        if "rottentomatoes" in required_sources and (
            "rottentomatoes" in tags or any(tag.startswith("rt-") for tag in tags)
        ):
            return True
        if "nzbgeek" in required_sources and (
            "nzbgeek" in tags or "nzbgeek-rss" in tags
        ):
            return True
        if "drunkenslug" in required_sources and "drunkenslug" in tags:
            return True
        if "rogerebert" in required_sources and "rogerebert" in tags:
            return True
        if "releases" in required_sources and "releases" in tags:
            return True
        if "upcoming" in required_sources and "upcoming" in tags:
            return True
        if "plex" in required_sources and (movie.available_on_plex or "plex" in tags):
            return True
        if "radarr" in required_sources and (movie.available_on_radarr or "radarr" in tags):
            return True
        if "oscars" in required_sources and "oscars" in tags:
            return True
        if "criterion" in required_sources and "criterion" in tags:
            return True

        return False

    @staticmethod
    def _movie_matches_release_date(
        movie: MovieCandidate,
        release_date_from: date | None,
        release_date_to: date | None,
    ) -> bool:
        if release_date_from is None and release_date_to is None:
            return True
        release_date = Recommender._coerce_release_date(movie.release_date)
        if release_date is None:
            return False
        if release_date_from is not None and release_date < release_date_from:
            return False
        if release_date_to is not None and release_date > release_date_to:
            return False
        return True

    @staticmethod
    def _coerce_release_date(raw: str | None) -> date | None:
        if not raw:
            return None
        value = raw.strip()
        if not value:
            return None
        try:
            if "T" in value:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None

    async def _score_movie(
        self,
        user_id: str,
        movie: MovieCandidate,
    ) -> tuple[float, list[RecommendationReason]]:
        reasons: list[RecommendationReason] = []

        oscar_component = 0.0
        if "best-picture-winner" in movie.source_tags:
            oscar_component = 1.0
        elif "best-picture-nominee" in movie.source_tags:
            oscar_component = 0.7
        elif "oscars" in movie.source_tags:
            oscar_component = 0.4

        if oscar_component > 0:
            reasons.append(
                RecommendationReason(
                    label="Oscars",
                    value=round(oscar_component, 3),
                    detail="Award prestige signal from Oscars source.",
                )
            )

        criterion_component = 1.0 if "criterion" in movie.source_tags else 0.0
        if criterion_component > 0:
            reasons.append(
                RecommendationReason(
                    label="Criterion",
                    value=criterion_component,
                    detail="Included in Criterion Collection.",
                )
            )

        critic_component, critic_reason = self._critic_component(movie)
        if critic_component > 0 and critic_reason:
            reasons.append(
                RecommendationReason(
                    label="Critic rating",
                    value=round(critic_component, 3),
                    detail=critic_reason,
                )
            )

        upcoming_component = self._upcoming_component(movie)
        if upcoming_component > 0:
            reasons.append(
                RecommendationReason(
                    label="Upcoming",
                    value=round(upcoming_component, 3),
                    detail="Prioritized because release is upcoming.",
                )
            )

        releases_component = self._releases_component(movie)
        if releases_component > 0:
            reasons.append(
                RecommendationReason(
                    label="Releases.com",
                    value=round(releases_component, 3),
                    detail="Upcoming release signal sourced from Releases.com.",
                )
            )

        availability_component = self._availability_component(movie)
        if availability_component > 0:
            reasons.append(
                RecommendationReason(
                    label="Availability",
                    value=round(availability_component, 3),
                    detail="Boosted because title is accessible in your stack.",
                )
            )

        preference_component, nearest = await self._memory_store.preference_similarity(
            user_id=user_id,
            title=movie.title,
            overview=movie.overview,
            genres=movie.genres,
            top_k=3,
        )
        if nearest:
            examples = ", ".join(
                f"{entry.title} ({'liked' if entry.liked else 'disliked'})"
                for entry in nearest[:2]
            )
            reasons.append(
                RecommendationReason(
                    label="Preference memory",
                    value=round(preference_component, 3),
                    detail=f"Similarity to your history: {examples}",
                )
            )

        liked_rag_component, liked_matches = await self._memory_store.liked_rag_similarity(
            user_id=user_id,
            title=movie.title,
            overview=movie.overview,
            genres=movie.genres,
            top_k=3,
        )
        if liked_matches:
            examples = ", ".join(entry.title for entry in liked_matches[:2])
            reasons.append(
                RecommendationReason(
                    label="Liked RAG",
                    value=round(liked_rag_component, 3),
                    detail=f"Semantic match with liked movies: {examples}",
                )
            )

        unusual_component = 1.0 if "unusual-discovery" in movie.source_tags else 0.0
        if unusual_component > 0:
            reasons.append(
                RecommendationReason(
                    label="Usenet discovery",
                    value=1.0,
                    detail="Surfaced as an unusual release from Usenet feed.",
                )
            )

        poster_component = 1.0 if bool(movie.poster_url) else 0.0
        if poster_component > 0:
            reasons.append(
                RecommendationReason(
                    label="Poster art",
                    value=poster_component,
                    detail="Poster image available for a richer browse experience.",
                )
            )

        # Small boost for titles appearing in multiple agents.
        source_span = min(len(movie.source_tags) / 6.0, 1.0)

        score = (
            oscar_component * 0.10
            + criterion_component * 0.10
            + critic_component * 0.18
            + upcoming_component * 0.08
            + releases_component * 0.06
            + availability_component * 0.16
            + preference_component * 0.08
            + liked_rag_component * 0.08
            + unusual_component * 0.03
            + poster_component * 0.03
            + source_span * 0.10
        )

        tags = set(movie.source_tags)
        awards_only = tags and tags.issubset({"oscars", "best-picture-winner", "best-picture-nominee"})
        if awards_only and not (
            movie.available_on_plex
            or movie.available_on_radarr
            or movie.available_on_usenet
            or movie.release_date
            or movie.poster_url
        ):
            score -= 0.15

        return score, reasons

    @staticmethod
    def _availability_component(movie: MovieCandidate) -> float:
        value = 0.0
        if movie.available_on_plex:
            value += 0.6
        if movie.available_on_radarr:
            value += 0.3
        if movie.available_on_usenet:
            value += 0.2
        return min(value, 1.0)

    @staticmethod
    def _upcoming_component(movie: MovieCandidate) -> float:
        if not movie.release_date:
            return 0.0

        try:
            release = datetime.fromisoformat(movie.release_date.replace("Z", "+00:00")).date()
        except ValueError:
            return 0.2 if "upcoming" in movie.source_tags else 0.0

        today = datetime.now(UTC).date()
        days = (release - today).days
        if days < 0:
            return 0.0
        if days <= 14:
            return 1.0
        if days <= 45:
            return 0.7
        if days <= 90:
            return 0.4
        return 0.2

    @staticmethod
    def _rotten_tomatoes_component(movie: MovieCandidate) -> float:
        tags = set(movie.source_tags)
        if "rt-95plus" in tags:
            return 1.0
        if "rt-90plus" in tags:
            return 0.85
        if "rt-80plus" in tags:
            return 0.65
        if "rottentomatoes" in tags:
            return 0.35
        return 0.0

    @staticmethod
    def _critic_component(movie: MovieCandidate) -> tuple[float, str | None]:
        if movie.rottentomatoes_score is not None:
            rating = max(0, min(movie.rottentomatoes_score, 100))
            return rating / 100.0, f"Rotten Tomatoes: {rating}%"

        if movie.rogerebert_score is not None:
            score = movie.rogerebert_score
            if score <= 4.0:
                normalized = max(0.0, min(score / 4.0, 1.0))
                return normalized, f"RogerEbert: {score:.1f}/4"
            if score <= 5.0:
                normalized = max(0.0, min(score / 5.0, 1.0))
                return normalized, f"RogerEbert: {score:.1f}/5"
            normalized = max(0.0, min(score / 100.0, 1.0))
            return normalized, f"RogerEbert: {score:.1f}"

        fallback = Recommender._rotten_tomatoes_component(movie)
        if fallback > 0:
            return fallback, "Rotten Tomatoes consensus tags"
        return 0.0, None

    @staticmethod
    def _releases_component(movie: MovieCandidate) -> float:
        if "releases" not in set(movie.source_tags):
            return 0.0
        upcoming_component = Recommender._upcoming_component(movie)
        if upcoming_component > 0:
            return min(1.0, 0.3 + (upcoming_component * 0.7))
        return 0.35
