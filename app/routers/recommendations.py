from __future__ import annotations

import json
import logging
import random
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Query
from starlette.responses import StreamingResponse

from app import state
from app.config import limits, settings
from app.models import RecommendationResponse
from app.clients.ollama_client import OllamaClient
from app.clients.tmdb_client import TMDBClient
from app.services.mood_engine import get_all_moods, get_mood, infer_user_moods

logger = logging.getLogger(__name__)
router = APIRouter()

project_root = Path(__file__).resolve().parent.parent.parent


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_sources_query(raw_sources: str | None) -> set[str] | None:
    if not raw_sources:
        return None
    parts = {p.strip().lower() for p in raw_sources.split(",") if p.strip()}
    return parts or None


def _parse_date_query(raw: str | None) -> date | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _normalize_release_date(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        if "T" in value:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None


def _movie_source_keys(movie, agent_name: str) -> set[str]:
    tags = {tag.lower() for tag in movie.source_tags}
    keys = set(tags)
    keys.add(agent_name.lower())
    if any(tag.startswith("rt-") for tag in tags) or "rottentomatoes" in tags:
        keys.add("rt")
        keys.add("rottentomatoes")
    if "nzbgeek-rss" in tags:
        keys.add("nzbgeek")
    if "drunkenslug" in tags:
        keys.add("drunkenslug")
    if "criterion-release" in tags:
        keys.add("criterion")
    if movie.available_on_usenet:
        keys.add("usenet")
    if movie.available_on_plex:
        keys.add("plex")
    if movie.available_on_radarr:
        keys.add("radarr")
    return keys


def _build_release_calendar(
    source_movies: dict,
    required_sources: set[str] | None = None,
    release_date_from: date | None = None,
    release_date_to: date | None = None,
) -> list[dict]:
    merged: dict[str, dict] = {}
    for agent_name, movies in source_movies.items():
        for movie in movies:
            release_date = _normalize_release_date(movie.release_date)
            if not release_date:
                continue
            release_day = _parse_date_query(release_date)
            if release_day is None:
                continue
            if release_date_from is not None and release_day < release_date_from:
                continue
            if release_date_to is not None and release_day > release_date_to:
                continue
            source_keys = _movie_source_keys(movie, agent_name)
            if required_sources and source_keys.isdisjoint(required_sources):
                continue
            key = f"{movie.title.strip().lower()}::{movie.year if movie.year is not None else 'na'}::{release_date}"
            if key not in merged:
                merged[key] = {"title": movie.title, "year": movie.year, "release_date": release_date, "poster_url": movie.poster_url, "sources": set(source_keys)}
            else:
                merged[key]["sources"] = merged[key]["sources"].union(source_keys)
                if not merged[key].get("poster_url") and movie.poster_url:
                    merged[key]["poster_url"] = movie.poster_url

    rows = [{"title": r["title"], "year": r["year"], "release_date": r["release_date"], "poster_url": r["poster_url"], "sources": sorted(r["sources"])} for r in merged.values()]
    rows.sort(key=lambda item: (item["release_date"], item["title"].lower()))
    return rows


def _apply_enrichment_cache(recommendations: list) -> list:
    for rec in recommendations:
        movie = rec.movie if hasattr(rec, "movie") else rec.get("movie")
        if not movie:
            continue
        title = movie.title if hasattr(movie, "title") else movie.get("title")
        year = movie.year if hasattr(movie, "year") else movie.get("year")
        if not title:
            continue
        cached = state.memory_store.get_movie_cache(title, year)
        if cached:
            if hasattr(movie, "poster_url"):
                if not movie.poster_url and cached.get("poster_url"):
                    movie.poster_url = cached["poster_url"]
                if not movie.overview and cached.get("overview"):
                    movie.overview = cached["overview"]
                if cached.get("available_usenet"):
                    movie.available_on_usenet = True
            else:
                if not movie.get("poster_url") and cached.get("poster_url"):
                    movie["poster_url"] = cached["poster_url"]
                if not movie.get("overview") and cached.get("overview"):
                    movie["overview"] = cached["overview"]
                if cached.get("available_usenet"):
                    movie["available_on_usenet"] = True
        else:
            state.memory_store.set_movie_cache(title=title, year=year)
    return recommendations


def _prefilter_by_mood_genres(movie_list: list[dict], mood_name: str) -> list[dict]:
    mood_genre_rules = {
        "cozy": {"require": {"Comedy", "Drama", "Family", "Romance", "Animation", "Music"}, "prefer": {"Comedy", "Family", "Romance", "Animation"}, "avoid": {"Horror", "Thriller", "War", "Crime", "Action"}},
        "funny": {"require": {"Comedy"}, "prefer": {"Comedy"}, "avoid": {"Horror", "Thriller", "War", "Crime", "Drama"}},
        "thrilling": {"require": {"Thriller", "Action", "Horror", "Mystery", "Crime"}, "prefer": {"Thriller", "Action", "Horror"}, "avoid": {"Comedy", "Family", "Animation", "Romance", "Music"}},
        "romantic": {"require": {"Romance"}, "prefer": {"Romance", "Drama"}, "avoid": {"Horror", "Action", "War", "Crime", "Thriller"}},
        "dark": {"require": {"Crime", "Thriller", "Mystery", "Drama", "Horror"}, "prefer": {"Crime", "Thriller", "Horror"}, "avoid": {"Comedy", "Family", "Animation", "Music"}},
        "feel-good": {"require": {"Comedy", "Family", "Animation", "Music", "Romance"}, "prefer": {"Comedy", "Family", "Animation"}, "avoid": {"Horror", "Thriller", "War", "Crime"}},
        "mind-bending": {"require": {"Sci-Fi", "Mystery", "Thriller"}, "prefer": {"Sci-Fi", "Mystery"}, "avoid": {"Comedy", "Family", "Animation", "Romance"}},
        "nostalgic": {"require": set(), "prefer": set(), "avoid": set()},
        "adventurous": {"require": {"Adventure", "Action", "Fantasy", "Sci-Fi"}, "prefer": {"Adventure", "Fantasy"}, "avoid": {"Documentary"}},
        "inspiring": {"require": {"Drama", "Documentary", "History"}, "prefer": {"Drama", "History"}, "avoid": {"Horror", "Crime"}},
    }
    rules = mood_genre_rules.get(mood_name, {"require": set(), "prefer": set(), "avoid": set()})
    require_genres = rules.get("require", set())
    prefer_genres = rules.get("prefer", set())
    avoid_genres = rules.get("avoid", set())

    filtered = []
    for m in movie_list:
        genres = set(m.get("genres", []))
        if not genres:
            continue
        if require_genres and not (genres & require_genres):
            continue
        if avoid_genres and (genres & avoid_genres):
            continue
        filtered.append(m)

    if len(filtered) < 5:
        filtered = [m for m in movie_list if set(m.get("genres", [])) and (not require_genres or (set(m.get("genres", [])) & require_genres))]

    filtered.sort(key=lambda m: len(set(m.get("genres", [])) & prefer_genres) * 2 - len(set(m.get("genres", [])) & avoid_genres), reverse=True)
    return filtered


async def _llm_filter_by_mood(mood, movie_list: list[dict], count: int) -> list[int]:
    if not settings.ollama_base_url or not movie_list:
        return []
    prefiltered = _prefilter_by_mood_genres(movie_list, mood.name)
    movies_text_parts = []
    idx_map: dict[int, int] = {}
    for prompt_idx, m in enumerate(prefiltered[:50]):
        genres = ", ".join(m["genres"][:3]) if m["genres"] else "Unknown"
        overview = m["overview"][:120] + "..." if len(m["overview"]) > 120 else m["overview"]
        movies_text_parts.append(f"{prompt_idx}. {m['title']} ({m['year'] or '?'}) [{genres}] - {overview or 'No description'}")
        idx_map[prompt_idx] = m["idx"]
    movies_text = "\n".join(movies_text_parts)

    mood_hints = {
        "cozy": "Select ONLY feel-good, heartwarming movies. Comedy, family, romance films. NO thrillers, horror, crime, or tense films.",
        "funny": "Select ONLY pure comedies. Movies that are genuinely funny and make people laugh. NO dramas, thrillers, or horror.",
        "thrilling": "Select suspenseful, tense films. Action, horror, mystery, crime thrillers.",
        "romantic": "Select love stories and romantic films. Romance, romantic comedies, relationship dramas.",
        "dark": "Select dark, intense films. Crime, noir, psychological thrillers, gritty dramas.",
        "feel-good": "Select uplifting, happy movies. Inspiring stories with positive endings. NO sad or dark films.",
        "mind-bending": "Select complex, twist-filled films. Sci-fi puzzles, psychological mysteries.",
        "nostalgic": "Select beloved classics and older films with retro charm.",
        "adventurous": "Select epic journeys and adventures. Fantasy, exploration, action adventures.",
        "inspiring": "Select triumph stories about overcoming odds. Biographical successes, sports victories.",
    }
    hint = mood_hints.get(mood.name, "")
    prompt = f"""Select {count} movies that perfectly match "{mood.display_name}" mood.\n\n{hint}\n\nMovie list:\n{movies_text}\n\nReply with ONLY the numbers of your selections, separated by commas.\nExample: 0, 3, 7, 12\n\nSelected movies:"""

    try:
        client = OllamaClient(base_url=settings.ollama_base_url, model=settings.ollama_model, timeout_seconds=30.0)
        response = await client.generate(prompt=prompt, system="You are a movie expert. Output only comma-separated numbers. No explanations.")
        indices: list[int] = []
        clean_response = "".join(c if c.isdigit() or c in ", \n" else " " for c in response)
        for part in clean_response.replace("\n", ",").split(","):
            part = part.strip()
            if part.isdigit():
                prompt_idx = int(part)
                if prompt_idx in idx_map:
                    original_idx = idx_map[prompt_idx]
                    if original_idx not in indices:
                        indices.append(original_idx)
                        if len(indices) >= count:
                            break
        return indices
    except Exception as exc:
        logger.warning(f"LLM mood filter failed: {exc}")
        return []


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/api/recommendations", response_model=RecommendationResponse)
async def get_recommendations(
    user_id: str = Query(default="default"),
    count: int = Query(default=200, ge=1, le=limits.recommendations_max),
    offset: int = Query(default=0, ge=0),
    sort: str | None = Query(default=None),
    sources: str | None = Query(default=None),
    release_from: str | None = Query(default=None),
    release_to: str | None = Query(default=None),
    year_from: int | None = Query(default=None),
    year_to: int | None = Query(default=None),
) -> RecommendationResponse:
    required_sources = _parse_sources_query(sources)
    release_date_from = _parse_date_query(release_from)
    release_date_to = _parse_date_query(release_to)
    if release_date_from and release_date_to and release_date_from > release_date_to:
        release_date_from, release_date_to = release_date_to, release_date_from
    fetch_count = count + offset
    response = await state.swarm.recommend_filtered(
        user_id=user_id, count=fetch_count, sort_mode=sort, required_sources=required_sources,
        release_date_from=release_date_from, release_date_to=release_date_to, year_from=year_from, year_to=year_to,
    )
    if offset > 0 and response.recommendations:
        response.recommendations = response.recommendations[offset:]
    _apply_enrichment_cache(response.recommendations)
    return response


@router.get("/api/recommendations/stream")
async def stream_recommendations(
    user_id: str = Query(default="default"),
    count: int = Query(default=200, ge=1, le=limits.recommendations_max),
) -> StreamingResponse:
    async def event_generator():
        cached = state.swarm.get_cached_recommendations(user_id, count)
        if cached:
            yield f"event: cached\ndata: {json.dumps({'count': len(cached.recommendations), 'source': 'cache'})}\n\n"
        async for update in state.swarm.stream_agent_updates(user_id, count):
            yield f"event: agent\ndata: {json.dumps(update)}\n\n"
        yield f"event: complete\ndata: {json.dumps({'status': 'done'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@router.get("/api/recommendations/mood/{mood_name}")
async def get_mood_recommendations(
    mood_name: str,
    user_id: str = Query(default="default"),
    count: int = Query(default=24, ge=1, le=limits.recommendations_max),
    year_from: int | None = Query(default=None),
    year_to: int | None = Query(default=None),
) -> dict:
    mood = get_mood(mood_name)
    if not mood:
        return {"ok": False, "error": f"Unknown mood: {mood_name}", "recommendations": []}

    response = await state.swarm.recommend_filtered(
        user_id=user_id, count=min(count * 4, 600), sort_mode=None, required_sources=None,
        release_date_from=None, release_date_to=None, year_from=year_from, year_to=year_to,
    )
    movie_list = [
        {"idx": idx, "title": rec.movie.title, "year": rec.movie.year, "genres": rec.movie.genres, "overview": (rec.movie.overview or "")[:200], "rec": rec}
        for idx, rec in enumerate(response.recommendations[:100])
    ]
    selected_indices = await _llm_filter_by_mood(mood, movie_list, count)

    mood_genre_rules = {
        "funny": {"Comedy"}, "cozy": {"Comedy", "Drama", "Family", "Romance", "Animation"},
        "romantic": {"Romance"}, "thrilling": {"Thriller", "Action", "Horror", "Mystery", "Crime"},
        "dark": {"Crime", "Thriller", "Mystery", "Horror"}, "feel-good": {"Comedy", "Family", "Animation", "Romance"},
        "mind-bending": {"Sci-Fi", "Mystery", "Thriller"}, "adventurous": {"Adventure", "Action", "Fantasy"},
        "inspiring": {"Drama", "Documentary", "History"},
    }

    transformed_recommendations: list[dict] = []
    for idx in selected_indices:
        if idx < len(movie_list):
            rec = movie_list[idx]["rec"]
            transformed_recommendations.append({"movie": rec.movie.model_dump(), "score": float(rec.score), "mood_score": 80.0, "reasons": [r.model_dump() for r in rec.reasons]})

    if len(transformed_recommendations) < count:
        required_genres = mood_genre_rules.get(mood_name, set())
        existing_titles = {r["movie"].get("title") for r in transformed_recommendations}
        for rec in response.recommendations:
            if len(transformed_recommendations) >= count:
                break
            movie = rec.movie
            if movie.title in existing_titles:
                continue
            if required_genres and not (set(movie.genres or []) & required_genres):
                continue
            existing_titles.add(movie.title)
            transformed_recommendations.append({"movie": movie.model_dump(), "score": float(rec.score), "mood_score": 60.0, "reasons": [r.model_dump() for r in rec.reasons]})

    return {
        "ok": True,
        "mood": {"name": mood.name, "display_name": mood.display_name, "emoji": mood.emoji, "description": mood.description},
        "recommendations": transformed_recommendations[:count],
        "total": len(transformed_recommendations),
    }


@router.get("/api/moods")
async def get_moods() -> dict:
    return {"ok": True, "moods": get_all_moods()}


@router.get("/api/moods/infer/{user_id}")
async def infer_moods_for_user(user_id: str) -> dict:
    try:
        feedback_history = state.memory_store.recent_feedback(user_id, limit=50)
        feedback_records = [{"liked": fb.get("liked", False), "genres": fb.get("genres", []), "title": fb.get("title", ""), "year": fb.get("year")} for fb in feedback_history]
        suggested_moods = infer_user_moods(feedback_records)
        return {"ok": True, "user_id": user_id, "suggested_moods": suggested_moods, "feedback_count": len(feedback_records)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "suggested_moods": []}


@router.get("/api/movie-of-the-day")
async def get_movie_of_the_day(user_id: str = Query(default="default")) -> dict:
    llm = await state.get_llm_client()
    if llm and llm.available:
        try:
            award_type = random.choice(["Oscar Best Picture", "Cannes Palme d'Or"])
            decade_start = random.choice([1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020])
            decade_end = min(decade_start + 9, 2025)
            prompt = f"""Pick ONE {award_type} winner from {decade_start}-{decade_end}.

Return ONLY valid JSON (no markdown, no code blocks):
{{"title": "Movie Title", "year": 1999, "director": "Director Name", "overview": "2-3 sentence description of why this film is significant", "genres": ["Drama", "Genre2"], "source": "{award_type} Winner"}}"""
            response = await llm.generate(prompt=prompt, system="You are a film expert. Return only valid JSON, no other text.", max_tokens=300)
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
            response = response.strip()
            movie_data = json.loads(response)
            movie_data["tagline"] = "Today's Featured Film"
            if state.poster_lookup_client and not movie_data.get("poster_url"):
                try:
                    poster_url = await state.poster_lookup_client.poster_for(title=movie_data.get("title", ""), year=movie_data.get("year"))
                    if poster_url:
                        movie_data["poster_url"] = poster_url
                except Exception as exc:
                    logger.warning(f"Poster lookup failed: {exc}")
            return {"ok": True, "movie": movie_data}
        except Exception as exc:
            logger.warning(f"LLM movie-of-the-day failed: {exc}")

    try:
        oscar_data_path = project_root / "data/oscars_best_picture.json"
        if oscar_data_path.exists():
            oscar_movies = json.loads(oscar_data_path.read_text())
            if oscar_movies:
                movie = random.choice(oscar_movies)
                title = movie.get("winner") or movie.get("title", "Unknown")
                return {"ok": True, "movie": {"title": title, "year": movie.get("year"), "overview": f"Oscar Best Picture Winner {movie.get('year')}", "genres": ["Drama"], "source": "Oscar Best Picture Winner", "tagline": "Today's Featured Film"}}
    except Exception:
        pass

    return {"ok": False, "movie": None}


@router.get("/api/cache/stats")
async def get_cache_stats() -> dict:
    return {"ok": True, "swarm": state.swarm.get_cache_stats()}


@router.post("/api/cache/clear")
async def clear_caches() -> dict:
    cleared = state.swarm.clear_caches()
    return {"ok": True, "cleared": cleared}


@router.get("/api/movies/year/{year}")
async def get_movies_by_year(
    year: int,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=limits.max_page_size),
) -> dict:
    if year < limits.min_year or year > limits.get_max_year():
        return {"ok": False, "error": "Invalid year", "movies": [], "total": 0}
    all_movies = await state.swarm.fetch_movies_for_year(year)
    start_idx = (page - 1) * per_page
    page_movies = all_movies[start_idx: start_idx + per_page]
    return {
        "ok": True, "year": year, "page": page, "per_page": per_page, "total": len(all_movies),
        "movies": [{"movie_id": m.movie_id, "title": m.title, "year": m.year, "poster_url": m.poster_url, "overview": m.overview, "release_date": m.release_date, "source_tags": m.source_tags, "rottentomatoes_score": m.rottentomatoes_score} for m in page_movies],
    }


@router.get("/api/release-calendar")
async def get_release_calendar(
    user_id: str = Query(default="default"),
    sources: str | None = Query(default=None),
    release_from: str | None = Query(default=None),
    release_to: str | None = Query(default=None),
    limit: int = Query(default=1500, ge=1, le=limits.browse_max),
) -> dict:
    required_sources = _parse_sources_query(sources)
    release_date_from = _parse_date_query(release_from)
    release_date_to = _parse_date_query(release_to)
    if release_date_from and release_date_to and release_date_from > release_date_to:
        release_date_from, release_date_to = release_date_to, release_date_from
    source_movies, _agent_statuses = await state.swarm.collect_sources(user_id=user_id, count=120)
    source_movies.pop("radarr", None)
    rows = _build_release_calendar(source_movies, required_sources=required_sources, release_date_from=release_date_from, release_date_to=release_date_to)
    source_counts: dict[str, int] = {}
    for row in rows:
        for source in row["sources"]:
            source_counts[source] = source_counts.get(source, 0) + 1
    return {"generated_at": datetime.now(UTC).isoformat(), "total_items": len(rows), "source_counts": source_counts, "items": rows[:limit]}


@router.get("/api/trailer")
async def get_trailer(title: str = Query(...), year: int | None = Query(default=None)) -> dict:
    if not settings.tmdb_api_key:
        return {"ok": False, "video_key": None, "message": "TMDB not configured"}
    try:
        tmdb = TMDBClient(api_key=settings.tmdb_api_key, timeout_seconds=settings.source_timeout_seconds)
        results = await tmdb.search_movie(query=title.strip(), year=year)
        if not results:
            return {"ok": False, "video_key": None, "message": "Movie not found"}
        tmdb_id = results[0].get("id")
        if not tmdb_id:
            return {"ok": False, "video_key": None, "message": "No TMDB ID"}
        videos = await tmdb.movie_videos(tmdb_id)
        for v in videos:
            if v.get("site", "").lower() == "youtube" and v.get("type", "").lower() == "trailer":
                return {"ok": True, "video_key": v["key"]}
        for v in videos:
            if v.get("site", "").lower() == "youtube" and v.get("type", "").lower() == "teaser":
                return {"ok": True, "video_key": v["key"]}
        for v in videos:
            if v.get("site", "").lower() == "youtube":
                return {"ok": True, "video_key": v["key"]}
        return {"ok": False, "video_key": None, "message": "No YouTube trailer found"}
    except Exception as exc:
        return {"ok": False, "video_key": None, "message": str(exc)}


@router.get("/api/search")
async def search_movies(q: str = Query(..., min_length=1), ai: bool = Query(default=False)) -> dict:
    query = q.strip()
    if ai and settings.ollama_base_url:
        try:
            ollama = OllamaClient(base_url=settings.ollama_base_url, model=settings.ollama_model, timeout_seconds=5.0)
            ai_prompt = f"""User is searching for movies with this query: "{query}"\n\nIf this is a natural language request, respond with 3-5 specific movie title suggestions, one per line.\nIf this is already a movie title, just respond with that title.\nOnly respond with movie titles, nothing else."""
            ai_response = await ollama.generate(ai_prompt)
            if ai_response:
                ai_titles = [line.strip() for line in ai_response.strip().split("\n") if line.strip()]
                if ai_titles:
                    query = ai_titles[0]
        except Exception:
            pass

    if not settings.tmdb_api_key:
        return {"ok": False, "results": [], "message": "TMDB not configured"}
    try:
        tmdb = TMDBClient(api_key=settings.tmdb_api_key, timeout_seconds=settings.source_timeout_seconds)
        raw = await tmdb.search_movie(query=query)
        results = []
        for m in raw[:20]:
            poster_path = m.get("poster_path")
            backdrop_path = m.get("backdrop_path")
            release = m.get("release_date") or ""
            year = int(release[:4]) if len(release) >= 4 else None
            results.append({
                "tmdb_id": m.get("id"), "title": m.get("title"), "year": year, "overview": m.get("overview", ""),
                "poster_url": f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None,
                "backdrop_url": f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else None,
                "vote_average": m.get("vote_average"), "release_date": release,
            })
        return {"ok": True, "results": results, "query": query}
    except Exception as exc:
        return {"ok": False, "results": [], "message": str(exc)}


@router.get("/api/poster")
async def get_poster(
    title: str = Query(...),
    year: int | None = Query(default=None),
    force: str | None = Query(default=None),
) -> dict:
    if not state.swarm or not state.swarm._poster_lookup_client:
        return {"ok": False, "message": "Poster lookup not configured"}
    try:
        client = state.swarm._poster_lookup_client
        if force:
            cache_key = f"{title.strip()} {year or ''}".lower().strip()
            client._cache.pop(cache_key, None)
            variations = [title]
            clean_title = title.replace(":", "").replace("-", " ").strip()
            if clean_title != title:
                variations.append(clean_title)
            if ":" in title:
                variations.append(title.split(":")[0].strip())
            for var in variations:
                info = await client.lookup(var, year)
                if info and info.get("poster_url"):
                    return {"ok": True, **info}
                if year:
                    info = await client.lookup(var, None)
                    if info and info.get("poster_url"):
                        return {"ok": True, **info}
            return {"ok": False, "message": "No poster found after retries"}
        info = await client.lookup(title, year)
        if info:
            return {"ok": True, **info}
        return {"ok": False, "message": "No poster found"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
