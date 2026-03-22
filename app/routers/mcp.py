from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import state
from app.config import settings

router = APIRouter()

MCP_TOOLS = [
    {
        "name": "recommend_movies",
        "description": "Get personalized movie recommendations with AI-powered explanations",
        "icon": "🎬",
        "color": "#e50914",
        "params": [{"name": "count", "type": "number", "default": 5, "label": "Number of recommendations"}],
    },
    {
        "name": "explain_movie",
        "description": "Get a detailed AI explanation of why a movie is worth watching",
        "icon": "💡",
        "color": "#fbbf24",
        "params": [{"name": "title", "type": "string", "required": True, "label": "Movie title"}],
    },
    {
        "name": "search_movies",
        "description": "Search for movies by title, genre, year, or other criteria",
        "icon": "🔍",
        "color": "#06b6d4",
        "params": [
            {"name": "query", "type": "string", "required": True, "label": "Search query"},
            {"name": "year_from", "type": "number", "label": "Year from"},
            {"name": "year_to", "type": "number", "label": "Year to"},
        ],
    },
    {
        "name": "analyze_taste",
        "description": "Analyze a user's movie taste based on their feedback history",
        "icon": "📊",
        "color": "#8b5cf6",
        "params": [],
    },
    {
        "name": "movie_deep_dive",
        "description": "Comprehensive AI analysis of a movie's themes, style, and cultural impact",
        "icon": "🎯",
        "color": "#22c55e",
        "params": [{"name": "title", "type": "string", "required": True, "label": "Movie title"}],
    },
]


class MCPInvokeRequest(BaseModel):
    tool: str
    arguments: dict = Field(default_factory=dict)
    user_id: str = "default"
    provider: str | None = None


@router.get("/api/mcp/tools")
async def list_mcp_tools() -> dict:
    llm = await state.get_llm_client()
    return {
        "ok": True,
        "tools": MCP_TOOLS,
        "llm_available": llm is not None and llm.available,
        "llm_provider": llm.provider if llm and llm.available else None,
        "groq_available": llm.groq_available if llm else False,
        "groq_model": settings.groq_model,
        "ollama_available": llm.ollama_available if llm else False,
        "ollama_model": settings.ollama_model,
    }


@router.post("/api/mcp/invoke")
async def invoke_mcp_tool(payload: MCPInvokeRequest) -> dict:
    tool_name = payload.tool
    args = payload.arguments
    user_id = payload.user_id
    provider = payload.provider

    dispatch = {
        "recommend_movies": lambda: _mcp_recommend(args, user_id),
        "explain_movie": lambda: _mcp_explain(args, user_id, provider),
        "search_movies": lambda: _mcp_search(args),
        "analyze_taste": lambda: _mcp_analyze_taste(user_id, provider),
        "movie_deep_dive": lambda: _mcp_deep_dive(args, provider),
    }
    handler = dispatch.get(tool_name)
    if not handler:
        return {"ok": False, "error": f"Unknown tool: {tool_name}"}
    return await handler()


async def _mcp_recommend(args: dict, user_id: str) -> dict:
    count = min(max(args.get("count", 5), 1), 20)
    try:
        response = await state.swarm.recommend_filtered(
            user_id=user_id, count=count, sort_mode="score-desc",
            required_sources=None, release_date_from=None, release_date_to=None,
        )
        results = [
            {
                "title": rec.movie.title, "year": rec.movie.year,
                "explanation": rec.explanation or "No explanation available",
                "score": rec.movie.rottentomatoes_score, "genres": rec.movie.genres or [],
                "available": rec.movie.available_on_usenet, "poster": rec.movie.poster_url,
            }
            for rec in response.recommendations[:count]
        ]
        return {"ok": True, "recommendations": results}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def _mcp_explain(args: dict, user_id: str, provider: str | None = None) -> dict:
    title = args.get("title", "")
    if not title:
        return {"ok": False, "error": "Please provide a movie title"}
    llm = await state.get_llm_client(provider)
    if not llm or not llm.available:
        return {"ok": False, "error": "LLM not available for AI explanations"}
    prompt = f"""Why watch "{title}"? Give a concise 2-3 sentence pitch covering: what makes it special, who would enjoy it, and one standout element. Be specific, not generic."""
    try:
        response = await llm.generate(prompt, max_tokens=150)
        return {"ok": True, "title": title, "explanation": response}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def _mcp_search(args: dict) -> dict:
    query = args.get("query", "")
    year = args.get("year_from")
    if not query:
        return {"ok": False, "error": "Please provide a search query"}
    if not settings.tmdb_api_key:
        return {"ok": False, "error": "TMDB not configured"}
    try:
        from app.clients.tmdb_client import TMDBClient
        tmdb = TMDBClient(api_key=settings.tmdb_api_key, timeout_seconds=10.0)
        results = await tmdb.search_movie(query, year=year)
        matches = []
        for movie in results[:15]:
            release_date = movie.get("release_date", "")
            movie_year = int(release_date[:4]) if release_date and len(release_date) >= 4 else None
            poster = f"https://image.tmdb.org/t/p/w500{movie['poster_path']}" if movie.get("poster_path") else None
            matches.append({
                "title": movie.get("title", "Unknown"), "year": movie_year, "genres": [],
                "score": round(movie.get("vote_average", 0) * 10) if movie.get("vote_average") else None,
                "poster": poster, "overview": movie.get("overview", "")[:100],
            })
        return {"ok": True, "query": query, "results": matches}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def _mcp_analyze_taste(user_id: str, provider: str | None = None) -> dict:
    llm = await state.get_llm_client(provider)
    if not llm or not llm.available:
        return {"ok": False, "error": "LLM not available for taste analysis"}
    try:
        feedback = state.memory_store.recent_feedback(user_id, limit=30)
        if not feedback:
            return {"ok": False, "error": f"No feedback history found for user '{user_id}'"}
        liked = [f for f in feedback if f.liked]
        disliked = [f for f in feedback if not f.liked]
        prompt = (
            f"Movie taste analysis:\n"
            f"LIKED: {', '.join(f.title for f in liked[:10]) or 'None'}\n"
            f"DISLIKED: {', '.join(f.title for f in disliked[:5]) or 'None'}\n\n"
            f"In 3-4 sentences: summarize their taste profile, note patterns, and suggest 2 movies they'd enjoy."
        )
        response = await llm.generate(prompt, max_tokens=200)
        return {"ok": True, "user_id": user_id, "liked_count": len(liked), "disliked_count": len(disliked), "analysis": response}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def _mcp_deep_dive(args: dict, provider: str | None = None) -> dict:
    title = args.get("title", "")
    if not title:
        return {"ok": False, "error": "Please provide a movie title"}
    llm = await state.get_llm_client(provider)
    if not llm or not llm.available:
        return {"ok": False, "error": "LLM not available for deep analysis"}
    prompt = f"""Provide a comprehensive analysis of the film "{title}".

Structure your response as:

## Overview
Brief synopsis without major spoilers

## Themes & Ideas
The deeper themes, social commentary, or philosophical ideas explored

## Craft & Style
Notable aspects of direction, cinematography, editing, score, performances

## Cultural Impact
Its place in cinema history, influence, or cultural significance

## Who Should Watch
The ideal viewer and what mood/mindset suits this film

## Similar Films
3-5 films with similar appeal and brief explanation why

Be detailed, insightful, and specific. Avoid generic observations."""
    try:
        response = await llm.generate(prompt)
        return {"ok": True, "title": title, "analysis": response}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
