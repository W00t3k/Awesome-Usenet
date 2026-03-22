#!/usr/bin/env python3
"""
MCP Server for Majic Movie Selector.

Exposes movie recommendation tools via Model Context Protocol.
Run with: python mcp_server.py
"""

import asyncio
import json
import sys
from typing import Any

# MCP imports
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("MCP not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

# App imports - add app to path
sys.path.insert(0, "/Users/w00tock/Desktop/STuFF /Majic Movie selector")

from app.config import settings
from app.clients.llm_client import UnifiedLLMClient


# Initialize
server = Server("majic-movies")
swarm = None
llm_client: UnifiedLLMClient | None = None


async def get_swarm():
    """Lazy-load the swarm orchestrator with full agent set."""
    global swarm
    if swarm is None:
        # Import here to avoid circular imports
        from pathlib import Path
        from app.services.swarm import SwarmOrchestrator
        from app.services.recommender import Recommender
        from app.clients.poster_lookup_client import PosterLookupClient
        from app.clients.tmdb_client import TMDBClient
        from app.services.memory_store import MemoryStore
        from app.services.embedding import EmbeddingService

        # Import agents
        from app.agents.oscar_agent import OscarAgent
        from app.agents.criterion_agent import CriterionAgent
        from app.agents.rottentomatoes_agent import RottenTomatoesAgent
        from app.agents.rogerebert_agent import RogerEbertAgent
        from app.agents.upcoming_agent import UpcomingAgent
        from app.agents.releases_agent import ReleasesAgent
        from app.agents.imdb_top250_agent import IMDbTop250Agent
        from app.agents.a24_agent import A24Agent

        project_root = Path(__file__).resolve().parent

        embedding_service = EmbeddingService()
        memory = MemoryStore(settings.memory_db_path, embedding_service=embedding_service)
        recommender = Recommender(memory_store=memory)
        poster_client = PosterLookupClient(
            timeout_seconds=settings.source_timeout_seconds,
            tmdb_api_key=settings.tmdb_api_key,
            memory_store=memory,
        )
        tmdb_client = (
            TMDBClient(api_key=settings.tmdb_api_key, timeout_seconds=settings.source_timeout_seconds)
            if settings.tmdb_api_key
            else None
        )
        llm = await get_llm()

        # Build agents - subset of key sources for faster MCP responses
        agents = [
            OscarAgent(
                dataset_path=project_root / "data/oscars_best_picture.json",
                memory_store=memory,
                timeout_seconds=settings.source_timeout_seconds,
            ),
            CriterionAgent(
                dataset_path=project_root / "data/criterion_collection.json",
                memory_store=memory,
            ),
            IMDbTop250Agent(
                dataset_path=project_root / "data/imdb_top250.json",
                memory_store=memory,
            ),
            A24Agent(
                dataset_path=project_root / "data/a24_films.json",
                memory_store=memory,
            ),
            RottenTomatoesAgent(
                list_url=settings.rottentomatoes_list_url,
                timeout_seconds=settings.source_timeout_seconds,
                fallback_dataset_path=project_root / "data/rottentomatoes_seed.json",
            ),
            RogerEbertAgent(
                reviews_url=settings.rogerebert_reviews_url,
                timeout_seconds=settings.source_timeout_seconds,
                fallback_dataset_path=project_root / "data/rogerebert_seed.json",
            ),
            UpcomingAgent(
                tmdb_api_key=settings.tmdb_api_key,
                timeout_seconds=settings.source_timeout_seconds,
                fallback_dataset_path=project_root / "data/upcoming_seed.json",
            ),
            ReleasesAgent(
                releases_url=settings.releases_url,
                timeout_seconds=settings.source_timeout_seconds,
                fallback_dataset_path=project_root / "data/releases_seed.json",
            ),
        ]

        swarm = SwarmOrchestrator(
            agents=agents,
            recommender=recommender,
            poster_lookup_client=poster_client,
            tmdb_client=tmdb_client,
            llm_client=llm,
            memory_store=memory,
        )
    return swarm


async def get_llm() -> UnifiedLLMClient | None:
    """Get LLM client (Groq or Ollama)."""
    global llm_client
    if llm_client is None:
        llm_client = UnifiedLLMClient(
            groq_api_key=settings.groq_api_key,
            groq_model=settings.groq_model,
            ollama_base_url=settings.ollama_base_url,
            ollama_model=settings.ollama_model,
        )
    return llm_client if llm_client.available else None


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools."""
    return [
        Tool(
            name="recommend_movies",
            description="Get personalized movie recommendations with AI-powered explanations. Returns top picks based on user preferences and available sources.",
            inputSchema={
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "Number of recommendations (1-20)",
                        "default": 5,
                    },
                    "user_id": {
                        "type": "string",
                        "description": "User ID for personalization",
                        "default": "default",
                    },
                },
            },
        ),
        Tool(
            name="explain_movie",
            description="Get a detailed AI explanation of why a specific movie is worth watching. Provides verbose, insightful analysis.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Movie title to explain",
                    },
                    "user_id": {
                        "type": "string",
                        "description": "User ID for personalized explanation",
                        "default": "default",
                    },
                },
                "required": ["title"],
            },
        ),
        Tool(
            name="search_movies",
            description="Search for movies by title, genre, year, or other criteria.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (title, genre, director, etc.)",
                    },
                    "year_from": {
                        "type": "integer",
                        "description": "Minimum release year",
                    },
                    "year_to": {
                        "type": "integer",
                        "description": "Maximum release year",
                    },
                    "available_only": {
                        "type": "boolean",
                        "description": "Only show movies available for download",
                        "default": False,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="analyze_taste",
            description="Analyze a user's movie taste based on their feedback history. Returns insights about preferred genres, eras, and patterns.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "User ID to analyze",
                        "default": "default",
                    },
                },
            },
        ),
        Tool(
            name="movie_deep_dive",
            description="Get comprehensive AI analysis of a movie including themes, style, cultural impact, and who would enjoy it.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Movie title for deep analysis",
                    },
                },
                "required": ["title"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""

    if name == "recommend_movies":
        return await handle_recommend(arguments)
    elif name == "explain_movie":
        return await handle_explain(arguments)
    elif name == "search_movies":
        return await handle_search(arguments)
    elif name == "analyze_taste":
        return await handle_analyze_taste(arguments)
    elif name == "movie_deep_dive":
        return await handle_deep_dive(arguments)
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def handle_recommend(args: dict) -> list[TextContent]:
    """Get movie recommendations with AI explanations."""
    count = min(max(args.get("count", 5), 1), 20)
    user_id = args.get("user_id", "default")

    try:
        s = await get_swarm()
        response = await s.recommend_filtered(
            user_id=user_id,
            count=count,
            sort_mode="score-desc",
            required_sources=None,
            release_date_from=None,
            release_date_to=None,
        )

        results = []
        for i, rec in enumerate(response.recommendations[:count], 1):
            movie = rec.movie
            explanation = rec.explanation or "No explanation available"

            result = f"""
**{i}. {movie.title}** ({movie.year or 'Unknown year'})
- **Why watch:** {explanation}
- **RT Score:** {movie.rottentomatoes_score or 'N/A'}%
- **Genres:** {', '.join(movie.genres) if movie.genres else 'Unknown'}
- **Available:** {'Yes (Usenet)' if movie.available_on_usenet else 'Check streaming'}
"""
            results.append(result)

        output = f"# Top {count} Movie Recommendations\n\n" + "\n".join(results)
        return [TextContent(type="text", text=output)]

    except Exception as e:
        return [TextContent(type="text", text=f"Error getting recommendations: {e}")]


async def handle_explain(args: dict) -> list[TextContent]:
    """Generate detailed AI explanation for a movie."""
    title = args.get("title", "")
    user_id = args.get("user_id", "default")

    if not title:
        return [TextContent(type="text", text="Please provide a movie title")]

    llm = await get_llm()
    if not llm:
        return [TextContent(type="text", text="LLM not available for AI explanations")]

    prompt = f"""Provide a detailed, insightful explanation of why someone should watch "{title}".

Include:
1. What makes this film unique or noteworthy
2. The themes and ideas it explores
3. Notable aspects of direction, cinematography, or performances
4. What type of viewer would most appreciate it
5. How it compares to similar films

Be specific and avoid generic praise. Write 3-4 paragraphs."""

    try:
        response = await llm.generate(prompt)
        output = f"# Why Watch: {title}\n\n{response}"
        return [TextContent(type="text", text=output)]
    except Exception as e:
        return [TextContent(type="text", text=f"Error generating explanation: {e}")]


async def handle_search(args: dict) -> list[TextContent]:
    """Search for movies matching criteria."""
    query = args.get("query", "")
    year_from = args.get("year_from")
    year_to = args.get("year_to")
    available_only = args.get("available_only", False)

    try:
        s = await get_swarm()
        response = await s.recommend_filtered(
            user_id="search",
            count=50,
            sort_mode="score-desc",
            required_sources=None,
            release_date_from=None,
            release_date_to=None,
            year_from=year_from,
            year_to=year_to,
        )

        # Filter by query
        query_lower = query.lower()
        matches = []
        for rec in response.recommendations:
            movie = rec.movie
            # Match title, genres, or overview
            if (query_lower in movie.title.lower() or
                any(query_lower in g.lower() for g in movie.genres) or
                (movie.overview and query_lower in movie.overview.lower())):

                if available_only and not movie.available_on_usenet:
                    continue

                matches.append(f"- **{movie.title}** ({movie.year}) - {', '.join(movie.genres[:3])}")
                if len(matches) >= 15:
                    break

        if matches:
            output = f"# Search Results for '{query}'\n\n" + "\n".join(matches)
        else:
            output = f"No movies found matching '{query}'"

        return [TextContent(type="text", text=output)]

    except Exception as e:
        return [TextContent(type="text", text=f"Search error: {e}")]


async def handle_analyze_taste(args: dict) -> list[TextContent]:
    """Analyze user's movie taste using AI."""
    user_id = args.get("user_id", "default")

    llm = await get_llm()
    if not llm:
        return [TextContent(type="text", text="LLM not available for taste analysis")]

    # Get user's feedback history
    try:
        from app.services.memory_store import MemoryStore
        from app.services.embedding import EmbeddingService
        embedding_service = EmbeddingService()
        memory = MemoryStore(settings.memory_db_path, embedding_service=embedding_service)
        feedback = await memory.recent_feedback(user_id, limit=30)

        if not feedback:
            return [TextContent(type="text", text=f"No feedback history found for user '{user_id}'")]

        liked = [f for f in feedback if f.liked]
        disliked = [f for f in feedback if not f.liked]

        liked_titles = [f.title for f in liked[:10]]
        disliked_titles = [f.title for f in disliked[:5]]

        prompt = f"""Analyze this user's movie taste based on their ratings:

LIKED: {', '.join(liked_titles) if liked_titles else 'None yet'}
DISLIKED: {', '.join(disliked_titles) if disliked_titles else 'None yet'}

Provide insights about:
1. Their preferred genres and themes
2. Patterns in what they enjoy (era, style, tone)
3. What they seem to avoid
4. 3 specific movie recommendations based on this taste
5. A "taste profile" summary in one sentence

Be specific and insightful."""

        response = await llm.generate(prompt)
        output = f"# Taste Analysis for {user_id}\n\n{response}"
        return [TextContent(type="text", text=output)]

    except Exception as e:
        return [TextContent(type="text", text=f"Error analyzing taste: {e}")]


async def handle_deep_dive(args: dict) -> list[TextContent]:
    """Comprehensive AI analysis of a specific movie."""
    title = args.get("title", "")

    if not title:
        return [TextContent(type="text", text="Please provide a movie title")]

    llm = await get_llm()
    if not llm:
        return [TextContent(type="text", text="LLM not available for deep analysis")]

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
        output = f"# Deep Dive: {title}\n\n{response}"
        return [TextContent(type="text", text=output)]
    except Exception as e:
        return [TextContent(type="text", text=f"Error in deep dive: {e}")]


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
