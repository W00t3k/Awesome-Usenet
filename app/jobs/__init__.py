"""Background job queue using Redis and RQ."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from redis import Redis
    from rq import Queue

logger = logging.getLogger(__name__)

# Lazy-loaded Redis connection and queues
_redis_conn: "Redis | None" = None
_default_queue: "Queue | None" = None
_sync_queue: "Queue | None" = None


def get_redis_connection() -> "Redis":
    """Get or create Redis connection."""
    global _redis_conn
    if _redis_conn is None:
        try:
            from redis import Redis

            _redis_conn = Redis.from_url(
                settings.redis_url,
                decode_responses=True,
            )
            # Test connection
            _redis_conn.ping()
        except ImportError:
            logger.warning("redis package not installed - background jobs disabled")
            raise
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            raise
    return _redis_conn


def get_default_queue() -> "Queue":
    """Get default job queue."""
    global _default_queue
    if _default_queue is None:
        from rq import Queue

        _default_queue = Queue("default", connection=get_redis_connection())
    return _default_queue


def get_sync_queue() -> "Queue":
    """Get sync job queue (for catalog syncs)."""
    global _sync_queue
    if _sync_queue is None:
        from rq import Queue

        _sync_queue = Queue("sync", connection=get_redis_connection())
    return _sync_queue


def is_redis_available() -> bool:
    """Check if Redis is available."""
    try:
        get_redis_connection()
        return True
    except Exception:
        return False


def enqueue_sync_job(job_type: str) -> str | None:
    """Enqueue a catalog sync job.

    Args:
        job_type: One of 'oscars', 'criterion', 'usenet_poll'

    Returns:
        Job ID if queued, None if Redis unavailable
    """
    try:
        queue = get_sync_queue()
        if job_type == "usenet_poll":
            from app.jobs.tasks.usenet_poll import poll_usenet_releases

            job = queue.enqueue(poll_usenet_releases, job_timeout="5m")
        else:
            from app.jobs.tasks.catalog_sync import sync_catalog

            job = queue.enqueue(sync_catalog, job_type, job_timeout="10m")
        return job.id
    except Exception as e:
        logger.warning(f"Failed to enqueue sync job: {e}")
        return None
