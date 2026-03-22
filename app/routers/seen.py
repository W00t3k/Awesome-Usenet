from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app import state
from app.config import limits, settings
from app.models import FeedbackInput, FeedbackRow, SeenMovieDeleteInput, SeenMovieInput, SeenMovieRow

router = APIRouter()


class RagLikesQueryRequest(BaseModel):
    user_id: str = "default"
    query: str
    top_k: int = 8
    include_summary: bool = True


# ── Seen movies ────────────────────────────────────────────────────────────────

@router.get("/api/seen/{user_id}", response_model=list[SeenMovieRow])
async def get_seen_movies(
    user_id: str,
    limit: int = Query(default=500, ge=1, le=limits.seen_max),
    q: str | None = Query(default=None),
) -> list[SeenMovieRow]:
    return state.memory_store.list_seen(user_id=user_id, limit=limit, query=q)


@router.post("/api/seen")
async def add_seen_movie(payload: SeenMovieInput) -> dict:
    state.memory_store.upsert_seen(payload)
    return {"status": "ok"}


@router.delete("/api/seen")
async def remove_seen_movie(payload: SeenMovieDeleteInput) -> dict:
    removed = state.memory_store.remove_seen(user_id=payload.user_id, movie_id=payload.movie_id)
    return {"status": "ok", "removed": removed}


@router.post("/api/seen/import/plex")
async def import_seen_from_plex(
    user_id: str = Query(default="default"),
    server_id: int | None = Query(default=None),
) -> dict:
    from app.clients.plex_client import PlexClient
    from app.routers.plex import get_plex_config

    plex_config = get_plex_config(server_id)
    if not plex_config:
        return {"ok": False, "imported": 0, "message": "No Plex server configured"}
    base_url, token = plex_config
    if not token:
        return {"ok": False, "imported": 0, "message": "Plex token missing"}

    rows = await PlexClient(base_url=base_url, token=token, timeout_seconds=settings.source_timeout_seconds).library_movies()
    imported = 0
    for row in rows:
        title = row.get("title")
        if not title:
            continue
        rating_key = row.get("ratingKey")
        year = row.get("year")
        movie_id = (
            f"plex:{rating_key}"
            if rating_key
            else f"plex:{title.strip().lower().replace(' ', '_')}::{year if year is not None else 'na'}"
        )
        state.memory_store.upsert_seen(SeenMovieInput(user_id=user_id, movie_id=movie_id, title=title, year=year, source="plex"))
        imported += 1

    return {"ok": True, "imported": imported, "total": len(rows), "message": f"Imported {imported} movies from Plex library"}


# ── Feedback ───────────────────────────────────────────────────────────────────

@router.post("/api/feedback")
async def post_feedback(payload: FeedbackInput) -> dict:
    await state.memory_store.add_feedback(payload)
    category = "watch" if payload.liked else "skipped"
    state.memory_store.upsert_seen(
        SeenMovieInput(
            user_id=payload.user_id,
            movie_id=payload.movie_id,
            title=payload.title,
            year=payload.year,
            source=category,
        )
    )
    return {"status": "ok", "seen_source": category}


@router.get("/api/feedback/{user_id}", response_model=list[FeedbackRow])
async def get_feedback(user_id: str) -> list[FeedbackRow]:
    return state.memory_store.recent_feedback(user_id=user_id, limit=100)


# ── RAG likes ─────────────────────────────────────────────────────────────────

@router.get("/api/rag/likes/{user_id}")
async def rag_likes_snapshot(
    user_id: str,
    limit: int = Query(default=50, ge=1, le=limits.feedback_max),
) -> dict:
    rows = state.memory_store.recent_feedback(user_id=user_id, limit=limit * 3)
    liked_rows = [row for row in rows if row.liked][:limit]
    return {
        "ok": True,
        "user_id": user_id,
        "liked_count": state.memory_store.liked_feedback_count(user_id),
        "items": [row.model_dump() for row in liked_rows],
    }


@router.post("/api/rag/likes/query")
async def rag_query_likes(payload: RagLikesQueryRequest) -> dict:
    query = payload.query.strip()
    if not query:
        return {"ok": False, "message": "Query is required", "matches": []}

    matches = await state.memory_store.liked_rag_search(
        user_id=payload.user_id,
        query=query,
        top_k=payload.top_k,
    )
    summary = None
    if payload.include_summary:
        summary = await _llm_summarize_like_matches(query, matches)

    return {
        "ok": True,
        "user_id": payload.user_id,
        "query": query,
        "liked_count": state.memory_store.liked_feedback_count(payload.user_id),
        "matches": matches,
        "summary": summary,
    }


async def _llm_summarize_like_matches(query: str, matches: list[dict]) -> str | None:
    if not settings.ollama_base_url or not matches:
        return None
    try:
        from app.clients.ollama_client import OllamaClient
        client = OllamaClient(base_url=settings.ollama_base_url, model=settings.ollama_model, timeout_seconds=20.0)
        sample_lines = []
        for idx, match in enumerate(matches[:8], start=1):
            genres = ", ".join(match.get("genres") or [])
            sample_lines.append(
                f"{idx}. {match.get('title')} ({match.get('year') or '?'}) | "
                f"sim={float(match.get('similarity') or 0.0):.3f} | genres={genres or 'n/a'} | "
                f"note={str(match.get('note') or '')[:80]}"
            )
        prompt = (
            f"User taste query: {query}\n\nMatched liked movies:\n"
            + "\n".join(sample_lines)
            + "\n\nWrite 2 short sentences describing the user's likely taste for this query. Be concrete, no fluff."
        )
        response = await client.generate(prompt=prompt, system="You are a pragmatic recommendation analyst.")
        summary = (response or "").strip()
        return summary[:320] if summary else None
    except Exception:
        return None
