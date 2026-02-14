"""Usenet release polling task."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def poll_usenet_releases() -> dict:
    """Poll configured usenet indexers for new releases.

    This runs as a background job to keep the release cache fresh.
    """
    # Run async code in sync context
    return asyncio.run(_async_poll())


async def _async_poll() -> dict:
    """Async implementation of usenet polling."""
    from app.config import settings
    from app.clients.usenet_client import UsenetClient
    from app.services.usenet_parser import parse_and_deduplicate

    collected: list[str] = []
    errors: list[str] = []

    # Poll NZBGeek
    if settings.nzbgeek_rss_url and settings.nzbgeek_api_key:
        try:
            client = UsenetClient(
                base_url="https://api.nzbgeek.info",
                api_key=settings.nzbgeek_api_key,
                timeout_seconds=settings.source_timeout_seconds,
            )
            rows = await client.movie_rss_feed(
                rss_url=settings.nzbgeek_rss_url,
                api_key=settings.nzbgeek_api_key,
            )
            for row in rows:
                title = row.get("title", "").strip()
                if title:
                    collected.append(title)
            logger.info(f"Polled {len(rows)} items from NZBGeek")
        except Exception as e:
            errors.append(f"NZBGeek: {e}")
            logger.error(f"NZBGeek poll failed: {e}")

    # Poll DrunkenSlug
    if settings.drunkenslug_api_key:
        try:
            client = UsenetClient(
                base_url=settings.drunkenslug_base_url,
                api_key=settings.drunkenslug_api_key,
                timeout_seconds=settings.source_timeout_seconds,
            )
            rows = await client.movie_search(query="")
            for row in rows:
                title = (row.get("title") or row.get("name") or "").strip()
                if title:
                    collected.append(title)
            logger.info(f"Polled {len(rows)} items from DrunkenSlug")
        except Exception as e:
            errors.append(f"DrunkenSlug: {e}")
            logger.error(f"DrunkenSlug poll failed: {e}")

    # Parse and deduplicate
    if collected:
        parsed = parse_and_deduplicate(collected)
        logger.info(f"Parsed {len(parsed)} unique releases from {len(collected)} total")

        # Store in memory for quick access (optional - could use Redis cache)
        # For now just log the results
        return {
            "status": "success",
            "total_collected": len(collected),
            "unique_releases": len(parsed),
            "errors": errors,
        }

    return {
        "status": "no_data",
        "total_collected": 0,
        "unique_releases": 0,
        "errors": errors,
    }
