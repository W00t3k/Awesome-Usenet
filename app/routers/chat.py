from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import state

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = Field(default_factory=list)


class AIChatRequest(BaseModel):
    message: str
    context: str | None = None


class AIChatResponse(BaseModel):
    response: str
    sources_queried: list[str] = Field(default_factory=list)


# ── /api/chat/* ────────────────────────────────────────────────────────────────

@router.get("/api/chat/status")
async def chat_status() -> dict:
    """Check if AI chat is available."""
    llm = await state.get_llm_client()
    if llm and llm.available:
        return {"available": True, "provider": llm.provider}
    return {"available": False, "provider": None}


@router.post("/api/chat")
async def chat_with_ai(payload: ChatRequest) -> dict:
    """Chat with the AI assistant (standalone chat page)."""
    llm = await state.get_llm_client()
    if not llm or not llm.available:
        return {"response": None, "error": "AI not available. Configure Groq or Ollama in Settings."}

    system_prompt = (
        "You are a friendly and knowledgeable movie assistant. You help users discover films, "
        "provide recommendations, discuss cinema, and answer questions about movies, directors, "
        "actors, and the film industry. Keep responses concise but informative. Use a conversational tone."
    )

    messages = []
    for msg in payload.history[-6:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        messages.append(f"{'User' if role == 'user' else 'Assistant'}: {content}")
    messages.append(f"User: {payload.message}")
    prompt = "\n".join(messages) + "\nAssistant:"

    try:
        response = await llm.generate(prompt=prompt, system=system_prompt, max_tokens=500)
        return {"response": response.strip(), "provider": llm.provider}
    except Exception as exc:
        return {"response": None, "error": str(exc)}


# ── /api/ai/chat ───────────────────────────────────────────────────────────────

@router.post("/api/ai/chat")
async def ai_chat(payload: AIChatRequest) -> AIChatResponse:
    """Sidebar AI chat – supports Groq and Ollama, with optional usenet search."""
    llm = await state.get_llm_client()
    if not llm or not llm.available:
        return AIChatResponse(
            response="No AI provider is configured. Add a Groq API key or set up Ollama in Settings.",
            sources_queried=[],
        )

    message = payload.message.strip()
    sources_queried: list[str] = []

    usenet_keywords = [
        "drunkenslug", "nzbgeek", "usenet", "nzb", "indexer", "download", "available", "can i get",
    ]
    is_usenet_query = any(kw in message.lower() for kw in usenet_keywords)

    usenet_context = ""
    if is_usenet_query:
        from app.routers.usenet import query_usenet_sources, format_usenet_results
        stop_words = {
            "hey", "hi", "hello", "drunkenslug", "nzbgeek", "usenet", "can", "you", "do", "have",
            "any", "search", "find", "for", "the", "a", "an", "is", "there", "what", "about",
            "got", "looking", "download", "available", "get", "i",
        }
        search_terms = " ".join(
            w for w in message.split() if w.lower().strip("?,!.") not in stop_words
        )
        if search_terms:
            usenet_results = await query_usenet_sources(search_terms)
            sources_queried = [k for k, v in usenet_results.items() if v]
            usenet_context = format_usenet_results(usenet_results)

    if is_usenet_query:
        system_prompt = (
            "You are a helpful movie assistant for the Majic Movie Selector app. "
            "You help users find movies on usenet indexers like DrunkenSlug, NZBGeek, and other Newznab sources. "
            "When users ask about movie availability, summarize the search results helpfully. "
            "Be friendly and concise."
        )
    else:
        system_prompt = (
            "You are a knowledgeable movie expert assistant for the Majic Movie Selector app. "
            "You have extensive knowledge about movies, actors, directors, genres, and film history. "
            "When users ask about movies, actors, or recommendations, provide helpful and accurate information. "
            "Suggest specific movie titles when appropriate. Be conversational and enthusiastic about movies. "
            "Keep responses concise but informative - aim for 2-4 sentences unless more detail is needed."
        )

    user_prompt = message
    if usenet_context:
        user_prompt = (
            f"User question: {message}\n\n"
            f"Search results from usenet indexers:\n{usenet_context}\n\nSummarize these results for the user."
        )

    try:
        response = await llm.generate(prompt=user_prompt, system=system_prompt, max_tokens=500)
        return AIChatResponse(response=response.strip(), sources_queried=sources_queried)
    except Exception as exc:
        return AIChatResponse(
            response=f"Sorry, the AI request failed: {exc}",
            sources_queried=sources_queried,
        )
