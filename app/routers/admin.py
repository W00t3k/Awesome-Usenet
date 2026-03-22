from __future__ import annotations

import time
from datetime import UTC, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app import state
from app.config import settings

router = APIRouter()

_start_time = time.time()


def _format_uptime(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    elif seconds < 86400:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"
    else:
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        return f"{days}d {hours}h"


class ExplanationRequest(BaseModel):
    title: str
    year: int | None = None
    score: float = 0.0
    reasons: list[dict] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    overview: str | None = None


@router.get("/api/health")
async def health_check() -> dict:
    uptime = time.time() - _start_time
    return {
        "status": "ok",
        "uptime": _format_uptime(uptime),
        "uptime_seconds": round(uptime, 1),
        "timestamp": datetime.now(UTC).isoformat(),
        "version": "2.0",
    }


@router.get("/api/data-freshness")
async def get_data_freshness() -> dict:
    usenet_job = state.memory_store.last_sync_job("usenet_poll")
    oscars_job = state.memory_store.last_sync_job("oscars")
    criterion_job = state.memory_store.last_sync_job("criterion")

    timestamps = [
        j["completed_at"] for j in (usenet_job, oscars_job, criterion_job)
        if j and j.get("completed_at")
    ]
    most_recent = max(timestamps) if timestamps else None

    agent_count = len(state.swarm._agents) if state.swarm else 0
    agent_names = [a.name for a in state.swarm._agents] if state.swarm else []

    return {
        "ok": True,
        "most_recent": most_recent,
        "swarm": {"agent_count": agent_count, "agents": agent_names},
        "sources": {
            "usenet": {
                "last_sync": usenet_job["completed_at"] if usenet_job else None,
                "status": usenet_job["status"] if usenet_job else None,
                "interval_minutes": settings.usenet_poll_interval_minutes,
            },
            "oscars": {
                "last_sync": oscars_job["completed_at"] if oscars_job else None,
                "status": oscars_job["status"] if oscars_job else None,
                "items": oscars_job["items_processed"] if oscars_job else 0,
            },
            "criterion": {
                "last_sync": criterion_job["completed_at"] if criterion_job else None,
                "status": criterion_job["status"] if criterion_job else None,
                "items": criterion_job["items_processed"] if criterion_job else 0,
            },
        },
        "enrichment": state.enrichment_service.stats(),
    }


@router.get("/api/admin/sync-jobs")
async def list_sync_jobs(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    jobs = state.memory_store.recent_sync_jobs(limit=limit)
    return {"ok": True, "jobs": jobs}


@router.post("/api/admin/sync/{job_type}")
async def trigger_sync(job_type: str) -> dict:
    if job_type not in ("oscars", "criterion", "usenet_poll"):
        return {"ok": False, "message": f"Unknown job type: {job_type}"}
    try:
        from app.jobs import enqueue_sync_job, is_redis_available
        if is_redis_available():
            job_id = enqueue_sync_job(job_type)
            if job_id:
                return {"ok": True, "message": f"Sync job queued: {job_id}", "job_id": job_id}

        if job_type == "usenet_poll":
            from app.jobs.tasks.usenet_poll import poll_usenet_releases
            result = poll_usenet_releases()
        else:
            from app.jobs.tasks.catalog_sync import sync_catalog
            result = sync_catalog(job_type)
        return {"ok": True, "message": "Sync completed", "result": result}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


@router.get("/api/admin/users")
async def list_users(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    users = state.memory_store.list_users(limit=limit)
    return {"ok": True, "users": users}


@router.get("/api/admin/catalog-status")
async def get_catalog_status() -> dict:
    oscars_job = state.memory_store.last_sync_job("oscars")
    criterion_job = state.memory_store.last_sync_job("criterion")
    return {
        "ok": True,
        "oscars": {
            "last_sync": oscars_job["completed_at"] if oscars_job else None,
            "items": oscars_job["items_processed"] if oscars_job else 0,
        },
        "criterion": {
            "last_sync": criterion_job["completed_at"] if criterion_job else None,
            "items": criterion_job["items_processed"] if criterion_job else 0,
        },
    }


@router.post("/api/explain")
async def explain_recommendation(payload: ExplanationRequest) -> dict:
    try:
        from app.services.explainer import get_explainer
        explainer = get_explainer()
        explanation = await explainer.explain_recommendation(
            movie_title=payload.title, movie_year=payload.year, score=payload.score,
            reasons=payload.reasons, genres=payload.genres, overview=payload.overview,
        )
        return {"ok": True, "explanation": explanation}
    except Exception as exc:
        return {"ok": False, "explanation": None, "error": str(exc)}
