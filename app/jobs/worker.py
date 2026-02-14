#!/usr/bin/env python3
"""RQ Worker entry point.

Usage:
    python -m app.jobs.worker

Or with rq:
    rq worker default sync --url redis://localhost:6379/0
"""

from __future__ import annotations

import logging
import sys

from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Start RQ worker."""
    try:
        from redis import Redis
        from rq import Worker
    except ImportError:
        logger.error("redis and rq packages required. Install with: pip install rq redis")
        sys.exit(1)

    try:
        conn = Redis.from_url(settings.redis_url)
        conn.ping()
    except Exception as e:
        logger.error(f"Cannot connect to Redis at {settings.redis_url}: {e}")
        sys.exit(1)

    logger.info(f"Starting worker connected to {settings.redis_url}")
    logger.info("Listening on queues: default, sync")

    worker = Worker(["default", "sync"], connection=conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
