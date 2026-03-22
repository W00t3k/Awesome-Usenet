from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv, set_key
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import state
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Constants (duplicated from main for independence) ──────────────────────────

_project_root = Path(__file__).resolve().parent.parent.parent
_env_path = _project_root / ".env"
_env_example_path = _project_root / ".env.example"

DEFAULT_URLS: dict[str, str] = {
    "rottentomatoes_list_url": "https://www.rottentomatoes.com/browse/movies_at_home/sort:popular",
    "releases_url": "https://www.releases.com/calendar/movie",
    "plex_base_url": "http://localhost:32400",
    "radarr_base_url": "http://localhost:7878",
    "nzbgeek_rss_url": "https://api.nzbgeek.info/rss?t=search&cat=2000&apikey={API_KEY}",
    "drunkenslug_base_url": "https://drunkenslug.com/api",
    "usenet_base_url": "http://localhost:5076",
    "ollama_base_url": "http://localhost:11434",
    "ollama_model": "llama3.2:1b",
}

REQUIRED_URL_FIELDS = {
    "plex_base_url", "radarr_base_url", "drunkenslug_base_url", "usenet_base_url", "ollama_base_url",
}

ENV_KEY_MAP: dict[str, str] = {
    "google_client_id": "GOOGLE_CLIENT_ID",
    "google_client_secret": "GOOGLE_CLIENT_SECRET",
    "tmdb_api_key": "TMDB_API_KEY",
    "rottentomatoes_list_url": "ROTTENTOMATOES_LIST_URL",
    "releases_url": "RELEASES_URL",
    "plex_base_url": "PLEX_BASE_URL",
    "plex_token": "PLEX_TOKEN",
    "radarr_base_url": "RADARR_BASE_URL",
    "radarr_api_key": "RADARR_API_KEY",
    "nzbgeek_rss_url": "NZBGEEK_RSS_URL",
    "nzbgeek_api_key": "NZBGEEK_API_KEY",
    "drunkenslug_base_url": "DRUNKENSLUG_BASE_URL",
    "drunkenslug_api_key": "DRUNKENSLUG_API_KEY",
    "usenet_base_url": "USENET_BASE_URL",
    "usenet_api_key": "USENET_API_KEY",
    "ollama_base_url": "OLLAMA_BASE_URL",
    "ollama_model": "OLLAMA_MODEL",
    "groq_api_key": "GROQ_API_KEY",
    "groq_model": "GROQ_MODEL",
}

OPTIONAL_FIELDS = {
    "tmdb_api_key", "rottentomatoes_list_url", "releases_url", "plex_token", "radarr_api_key",
    "nzbgeek_rss_url", "nzbgeek_api_key", "drunkenslug_api_key", "usenet_api_key",
    "ollama_model", "groq_api_key", "groq_model",
}


# ── Pydantic models ────────────────────────────────────────────────────────────

class IntegrationSettingsPayload(BaseModel):
    tmdb_api_key: str | None = None
    rottentomatoes_list_url: str | None = None
    releases_url: str | None = None
    plex_base_url: str | None = None
    plex_token: str | None = None
    radarr_base_url: str | None = None
    radarr_api_key: str | None = None
    nzbgeek_rss_url: str | None = None
    nzbgeek_api_key: str | None = None
    drunkenslug_base_url: str | None = None
    drunkenslug_api_key: str | None = None
    usenet_base_url: str | None = None
    usenet_api_key: str | None = None
    ollama_base_url: str | None = None
    ollama_model: str | None = None
    groq_api_key: str | None = None
    groq_model: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None


class IntegrationTestRequest(BaseModel):
    integration: Literal[
        "tmdb", "rottentomatoes", "releases", "plex", "radarr",
        "nzbgeek", "drunkenslug", "usenet", "ollama", "groq", "google",
    ]
    values: IntegrationSettingsPayload | None = None


class OllamaPullRequest(BaseModel):
    model: str
    set_active: bool = True


class OllamaModelSelectRequest(BaseModel):
    model: str


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ensure_env_file() -> None:
    if _env_path.exists():
        return
    if _env_example_path.exists():
        _env_path.write_text(_env_example_path.read_text())
    else:
        _env_path.write_text("")


def to_public_settings_values() -> dict[str, str]:
    return {
        "tmdb_api_key": settings.tmdb_api_key or "",
        "rottentomatoes_list_url": settings.rottentomatoes_list_url or "",
        "releases_url": settings.releases_url or DEFAULT_URLS["releases_url"],
        "plex_base_url": settings.plex_base_url or DEFAULT_URLS["plex_base_url"],
        "plex_token": settings.plex_token or "",
        "radarr_base_url": settings.radarr_base_url or DEFAULT_URLS["radarr_base_url"],
        "radarr_api_key": settings.radarr_api_key or "",
        "nzbgeek_rss_url": settings.nzbgeek_rss_url or "",
        "nzbgeek_api_key": settings.nzbgeek_api_key or "",
        "drunkenslug_base_url": settings.drunkenslug_base_url or DEFAULT_URLS["drunkenslug_base_url"],
        "drunkenslug_api_key": settings.drunkenslug_api_key or "",
        "usenet_base_url": settings.usenet_base_url or DEFAULT_URLS["usenet_base_url"],
        "usenet_api_key": settings.usenet_api_key or "",
        "ollama_base_url": settings.ollama_base_url or DEFAULT_URLS["ollama_base_url"],
        "ollama_model": settings.ollama_model or DEFAULT_URLS["ollama_model"],
        "groq_api_key": settings.groq_api_key or "",
        "groq_model": settings.groq_model or "llama-3.3-70b-versatile",
    }


def effective_settings_values(overrides: dict[str, str | None] | None = None) -> dict[str, str]:
    values = to_public_settings_values()
    if not overrides:
        return values
    for field_name, raw_value in overrides.items():
        if field_name not in ENV_KEY_MAP:
            continue
        value = (raw_value or "").strip()
        if field_name in REQUIRED_URL_FIELDS and value == "":
            value = DEFAULT_URLS[field_name]
        values[field_name] = value
    return values


def save_settings(payload: dict[str, str | None]) -> None:
    _ensure_env_file()
    for field_name, raw_value in payload.items():
        if field_name not in ENV_KEY_MAP:
            continue
        value = (raw_value or "").strip()
        if field_name in REQUIRED_URL_FIELDS and value == "":
            value = DEFAULT_URLS[field_name]
        set_key(str(_env_path), ENV_KEY_MAP[field_name], value, quote_mode="never")
        if field_name in OPTIONAL_FIELDS and value == "":
            setattr(settings, field_name, None)
        else:
            setattr(settings, field_name, value)
    load_dotenv(dotenv_path=_env_path, override=True)


async def integration_status() -> dict[str, bool]:
    from app.clients.ollama_client import OllamaClient
    _rss = settings.nzbgeek_rss_url or ""
    _has_placeholder = "{API_KEY}" in _rss or "${API_KEY}" in _rss
    nzbgeek_configured = bool(_rss) and (not _has_placeholder or bool(settings.nzbgeek_api_key))

    async def _ollama_ok() -> bool:
        if not settings.ollama_base_url:
            return False
        try:
            client = OllamaClient(
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
                timeout_seconds=5.0,
            )
            return await client.is_connected()
        except Exception:
            return False

    return {
        "tmdb": bool(settings.tmdb_api_key),
        "rottentomatoes": bool(settings.rottentomatoes_list_url),
        "releases": bool(settings.releases_url),
        "plex": bool(settings.plex_token),
        "radarr": bool(settings.radarr_api_key),
        "nzbgeek": nzbgeek_configured,
        "drunkenslug": bool(settings.drunkenslug_api_key),
        "usenet": bool(settings.usenet_api_key),
        "ollama": await _ollama_ok(),
        "groq": bool(settings.groq_api_key),
    }


def _extract_ollama_model_names(models: list[dict]) -> list[str]:
    names: list[str] = []
    for model in models:
        name = str(model.get("name") or model.get("model") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _resolve_ollama_model_name(requested: str, models: list[dict]) -> str | None:
    requested = requested.strip()
    if not requested:
        return None
    names = _extract_ollama_model_names(models)
    if not names:
        return None
    rl = requested.lower()
    for name in names:
        if name.lower() == rl:
            return name
    base = rl.split(":")[0]
    for name in names:
        if name.lower().split(":")[0] == base:
            return name
    return None


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/api/settings")
async def get_settings() -> dict:
    return {"values": to_public_settings_values(), "defaults": DEFAULT_URLS}


@router.post("/api/settings")
async def save_settings_route(payload: IntegrationSettingsPayload) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    if updates:
        save_settings(updates)
        await state.reload_runtime()
    return {
        "status": "ok",
        "integrations": await integration_status(),
        "values": to_public_settings_values(),
    }


@router.get("/api/integrations")
async def get_integration_status() -> dict:
    return await integration_status()


@router.post("/api/integrations/test")
async def test_integration(payload: IntegrationTestRequest) -> dict:
    from app.clients.ollama_client import OllamaClient
    from app.clients.plex_client import PlexClient
    from app.clients.radarr_client import RadarrClient
    from app.clients.releases_client import ReleasesClient
    from app.clients.rottentomatoes_client import RottenTomatoesClient
    from app.clients.tmdb_client import TMDBClient
    from app.clients.usenet_client import UsenetClient

    integration = payload.integration
    values = effective_settings_values(
        payload.values.model_dump(exclude_unset=True) if payload.values else None
    )

    try:
        if integration == "google":
            client_id = values.get("google_client_id", "")
            client_secret = values.get("google_client_secret", "")
            if not client_id or not client_secret:
                return {"ok": False, "integration": integration, "message": "Client ID and Secret required"}
            if not client_id.endswith(".apps.googleusercontent.com"):
                return {"ok": False, "integration": integration, "message": "Invalid Client ID format"}
            if not client_secret.startswith("GOCSPX-"):
                return {"ok": False, "integration": integration, "message": "Invalid Client Secret format"}
            return {"ok": True, "integration": integration, "message": "Google OAuth credentials valid. Save to enable Sign in with Google."}

        if integration == "tmdb":
            if not values["tmdb_api_key"]:
                return {"ok": False, "integration": integration, "message": "TMDB_API_KEY missing"}
            rows = await TMDBClient(api_key=values["tmdb_api_key"], timeout_seconds=settings.source_timeout_seconds).upcoming_movies(page=1)
            return {"ok": True, "integration": integration, "message": f"TMDB reachable ({len(rows)} upcoming rows)"}

        if integration == "rottentomatoes":
            if not values["rottentomatoes_list_url"]:
                return {"ok": False, "integration": integration, "message": "ROTTENTOMATOES_LIST_URL missing"}
            rows = await RottenTomatoesClient(settings.source_timeout_seconds).browse_movies(values["rottentomatoes_list_url"])
            return {"ok": True, "integration": integration, "message": f"Rotten Tomatoes reachable ({len(rows)} parsed rows)"}

        if integration == "releases":
            if not values["releases_url"]:
                return {"ok": False, "integration": integration, "message": "RELEASES_URL missing"}
            rows = await ReleasesClient(settings.source_timeout_seconds).upcoming_movies(values["releases_url"])
            return {"ok": True, "integration": integration, "message": f"Releases.com reachable ({len(rows)} parsed rows)"}

        if integration == "plex":
            if not values["plex_token"]:
                return {"ok": False, "integration": integration, "message": "PLEX_TOKEN missing"}
            rows = await PlexClient(base_url=values["plex_base_url"], token=values["plex_token"], timeout_seconds=settings.source_timeout_seconds).library_movies()
            return {"ok": True, "integration": integration, "message": f"Plex reachable ({len(rows)} movies)"}

        if integration == "radarr":
            if not values["radarr_api_key"]:
                return {"ok": False, "integration": integration, "message": "RADARR_API_KEY missing"}
            rows = await RadarrClient(base_url=values["radarr_base_url"], api_key=values["radarr_api_key"], timeout_seconds=settings.source_timeout_seconds).movies()
            return {"ok": True, "integration": integration, "message": f"Download service reachable ({len(rows)} tracked movies)"}

        if integration == "nzbgeek":
            if not values["nzbgeek_rss_url"]:
                return {"ok": False, "integration": integration, "message": "NZBGEEK_RSS_URL missing"}
            if (("{API_KEY}" in values["nzbgeek_rss_url"] or "${API_KEY}" in values["nzbgeek_rss_url"]) and not values["nzbgeek_api_key"]):
                return {"ok": False, "integration": integration, "message": "NZBGEEK_API_KEY missing"}
            rows = await UsenetClient(base_url="https://api.nzbgeek.info", api_key=values["nzbgeek_api_key"] or "", timeout_seconds=settings.source_timeout_seconds).movie_rss_feed(rss_url=values["nzbgeek_rss_url"], api_key=values["nzbgeek_api_key"])
            return {"ok": True, "integration": integration, "message": f"NZBGeek RSS reachable ({len(rows)} items)"}

        if integration == "drunkenslug":
            if not values["drunkenslug_api_key"]:
                return {"ok": False, "integration": integration, "message": "DRUNKENSLUG_API_KEY missing"}
            rows = await UsenetClient(base_url=values["drunkenslug_base_url"], api_key=values["drunkenslug_api_key"], timeout_seconds=settings.source_timeout_seconds).movie_search(query="test")
            return {"ok": True, "integration": integration, "message": f"DrunkenSlug reachable ({len(rows)} rows)"}

        if integration == "usenet":
            if not values["usenet_api_key"]:
                return {"ok": False, "integration": integration, "message": "USENET_API_KEY missing"}
            rows = await UsenetClient(base_url=values["usenet_base_url"], api_key=values["usenet_api_key"], timeout_seconds=settings.source_timeout_seconds).movie_search(query="")
            return {"ok": True, "integration": integration, "message": f"Usenet indexer reachable ({len(rows)} rows)"}

        if integration == "ollama":
            if not values["ollama_base_url"]:
                return {"ok": False, "integration": integration, "message": "OLLAMA_BASE_URL missing"}
            client = OllamaClient(base_url=values["ollama_base_url"], model=values["ollama_model"], timeout_seconds=settings.source_timeout_seconds)
            health = await client.health_check()
            if not health.get("ok"):
                return {"ok": False, "integration": integration, "message": health.get("error", "Unable to connect to Ollama")}
            if not health["model_available"]:
                return {"ok": False, "integration": integration, "message": f"Ollama reachable ({health['models_count']} models) but model '{values['ollama_model']}' was not found"}
            return {"ok": True, "integration": integration, "message": f"Ollama reachable ({health['models_count']} models, {values['ollama_model']} available)"}

        if integration == "groq":
            api_key = values.get("groq_api_key", "")
            if not api_key:
                return {"ok": False, "integration": integration, "message": "GROQ_API_KEY required"}
            model = values.get("groq_model") or settings.groq_model or "llama-3.3-70b-versatile"
            from app.clients.groq_client import GroqClient
            success, message = await GroqClient(api_key=api_key, model=model).test_connection()
            return {"ok": success, "integration": integration, "message": message, "details": {"model_used": model}}

    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "integration": integration, "message": str(exc)}

    return {"ok": False, "integration": integration, "message": "Unsupported integration"}


# ── Ollama model management ─────────────────────────────────────────────────────

@router.get("/api/ollama/models")
async def list_ollama_models() -> dict:
    from app.clients.ollama_client import OllamaClient
    if not settings.ollama_base_url:
        return {"ok": False, "models": [], "message": "Ollama not configured"}
    try:
        models = await OllamaClient(base_url=settings.ollama_base_url, model=settings.ollama_model, timeout_seconds=10.0).list_models()
        return {"ok": True, "models": models, "current_model": settings.ollama_model}
    except Exception as exc:
        return {"ok": False, "models": [], "message": str(exc)}


@router.post("/api/ollama/model")
async def select_ollama_model(payload: OllamaModelSelectRequest) -> dict:
    from app.clients.ollama_client import OllamaClient
    if not settings.ollama_base_url:
        return {"ok": False, "message": "Ollama not configured"}
    requested = payload.model.strip()
    if not requested:
        return {"ok": False, "message": "Model name required"}
    try:
        models = await OllamaClient(base_url=settings.ollama_base_url, model=settings.ollama_model, timeout_seconds=10.0).list_models()
        resolved = _resolve_ollama_model_name(requested, models)
        if not resolved:
            preview = ", ".join(_extract_ollama_model_names(models)[:6]) or "none"
            return {"ok": False, "message": f"Model '{requested}' is not installed. Installed: {preview}"}
        save_settings({"ollama_model": resolved})
        await state.reload_runtime()
        return {"ok": True, "message": f"Active model set to '{resolved}'", "model": resolved}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


@router.post("/api/ollama/pull")
async def pull_ollama_model(payload: OllamaPullRequest) -> dict:
    import httpx
    if not settings.ollama_base_url:
        return {"ok": False, "message": "Ollama not configured"}
    model_name = payload.model.strip()
    if not model_name:
        return {"ok": False, "message": "Model name required"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=1800.0, write=1800.0, pool=10.0)) as client:
            response = await client.post(f"{settings.ollama_base_url}/api/pull", json={"name": model_name, "stream": False})
            if response.status_code == 200:
                resolved_model = model_name
                try:
                    tags = await client.get(f"{settings.ollama_base_url}/api/tags")
                    if tags.status_code == 200:
                        resolved = _resolve_ollama_model_name(model_name, tags.json().get("models", []) or [])
                        if resolved:
                            resolved_model = resolved
                except Exception:
                    pass
                if payload.set_active:
                    save_settings({"ollama_model": resolved_model})
                    await state.reload_runtime()
                    return {"ok": True, "message": f"Model '{resolved_model}' pulled and set as active model", "model": resolved_model, "active": True}
                return {"ok": True, "message": f"Model '{resolved_model}' pulled successfully", "model": resolved_model, "active": False}
            return {"ok": False, "message": f"Failed to pull: {response.text}"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
