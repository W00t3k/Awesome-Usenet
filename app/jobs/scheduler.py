"""Job scheduling setup using rq-scheduler."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.config import settings
from app.jobs import get_redis_connection, is_redis_available

if TYPE_CHECKING:
    from rq_scheduler import Scheduler

logger = logging.getLogger(__name__)


def get_scheduler() -> "Scheduler | None":
    """Get or create scheduler instance."""
    if not is_redis_available():
        return None

    try:
        from rq_scheduler import Scheduler

        return Scheduler(connection=get_redis_connection())
    except ImportError:
        logger.warning("rq-scheduler not installed")
        return None


def setup_scheduled_jobs() -> bool:
    """Configure scheduled sync jobs.

    Returns True if jobs were scheduled, False otherwise.
    """
    scheduler = get_scheduler()
    if not scheduler:
        logger.info("Scheduler not available - skipping scheduled jobs")
        return False

    from app.jobs.tasks.catalog_sync import sync_catalog
    from app.jobs.tasks.usenet_poll import poll_usenet_releases

    # Clear existing jobs first
    for job in scheduler.get_jobs():
        job_func = getattr(job.func, "__name__", str(job.func))
        if job_func in ("sync_catalog", "poll_usenet_releases"):
            scheduler.cancel(job)

    # Schedule Oscar sync (weekly on Sundays at 3am)
    # Default cron: "0 3 * * 0"
    scheduler.cron(
        settings.oscars_sync_cron,
        func=sync_catalog,
        args=["oscars"],
        id="sync_oscars",
        timeout=600,
    )
    logger.info(f"Scheduled oscars sync: {settings.oscars_sync_cron}")

    # Schedule Criterion sync (monthly on 1st at 4am)
    # Default cron: "0 4 1 * *"
    scheduler.cron(
        settings.criterion_sync_cron,
        func=sync_catalog,
        args=["criterion"],
        id="sync_criterion",
        timeout=600,
    )
    logger.info(f"Scheduled criterion sync: {settings.criterion_sync_cron}")

    # Schedule usenet polling (every N minutes)
    if settings.usenet_poll_interval_minutes > 0:
        scheduler.schedule(
            scheduled_time=datetime.utcnow() + timedelta(minutes=1),
            func=poll_usenet_releases,
            interval=settings.usenet_poll_interval_minutes * 60,
            id="poll_usenet",
            timeout=300,
        )
        logger.info(
            f"Scheduled usenet polling: every {settings.usenet_poll_interval_minutes} minutes"
        )

    return True


def run_scheduler() -> None:
    """Run the scheduler process (for rq-scheduler daemon)."""
    scheduler = get_scheduler()
    if not scheduler:
        logger.error("Scheduler not available")
        return

    setup_scheduled_jobs()
    scheduler.run()
