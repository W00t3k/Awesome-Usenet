from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from app.agents.base import MovieAgent
from app.clients.usenet_client import UsenetClient
from app.models import AgentContext, MovieCandidate, SourcePayload
from app.services.usenet_parser import parse_release

if TYPE_CHECKING:
    from app.services.swarm_context import SwarmContext

logger = logging.getLogger(__name__)


class UsenetAgent(MovieAgent):
    name = "nzbgeek"
    supports_llm = True  # Enable LLM features for smart search queries

    def __init__(self, rss_url: str | None, api_key: str | None, timeout_seconds: float):
        self._rss_url = rss_url
        self._api_key = api_key
        # base_url is not used for RSS mode; keep a harmless default for client construction.
        self._client = UsenetClient(base_url="https://api.nzbgeek.info", api_key=api_key or "", timeout_seconds=timeout_seconds)

    async def collect(self, context: AgentContext | SwarmContext) -> SourcePayload:
        if not self._rss_url:
            return SourcePayload(metadata={"notes": "NZBGEEK_RSS_URL missing; skipping NZBGeek RSS"})
        if self._requires_api_key(self._rss_url) and not self._api_key:
            return SourcePayload(
                metadata={"notes": "NZBGEEK_API_KEY missing for RSS URL template; skipping NZBGeek RSS"}
            )

        # Fetch RSS feed only (fast) - API search is done separately in Just Added section
        rows = await self._client.movie_rss_feed(self._rss_url, api_key=self._api_key)
        all_rows = rows
        movies: list[MovieCandidate] = []
        seen_titles: set[str] = set()

        for row in all_rows:
            raw_title = (row.get("title") or "").strip()
            if not raw_title:
                continue

            # Use enhanced parser
            parsed = parse_release(raw_title)
            if parsed.is_tv_release:
                continue

            # Deduplicate by title+year
            title_key = f"{parsed.title.lower()}:{parsed.year or 0}"
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)

            tags = ["nzbgeek", "usenet", "nzbgeek-rss"]
            if self._looks_unusual(parsed):
                tags.append("unusual-discovery")

            # Add quality info to tags
            if parsed.quality != "unknown":
                tags.append(parsed.quality)
            if parsed.is_hdr:
                tags.append("hdr")

            posted_at = str(
                row.get("pub_date")
                or row.get("pubDate")
                or row.get("posted")
                or row.get("usenetdate")
                or row.get("date")
                or ""
            ).strip()

            evidence = ["NZBGeek RSS release listing"]
            if posted_at:
                evidence.append(f"NZBGeek item date: {posted_at}")

            # Include quality details in evidence
            quality_info = []
            if parsed.quality != "unknown":
                quality_info.append(parsed.quality)
            if parsed.source != "unknown":
                quality_info.append(parsed.source)
            if parsed.codec != "unknown":
                quality_info.append(parsed.codec)
            if quality_info:
                evidence.append(f"Quality: {' '.join(quality_info)}")

            movies.append(
                MovieCandidate(
                    movie_id=f"nzbgeek:{hashlib.sha1(raw_title.encode('utf-8')).hexdigest()[:12]}",
                    title=parsed.title,
                    year=parsed.year,
                    overview=row.get("description"),
                    source_tags=tags,
                    evidence=evidence,
                    available_on_usenet=True,
                )
            )

        # Share discoveries with other agents if SwarmContext
        if hasattr(context, "collaborate"):
            unusual_titles = [m.title for m in movies if "unusual-discovery" in m.source_tags]
            if unusual_titles:
                await context.collaborate(
                    agent_name=self.name,
                    message=f"Found {len(unusual_titles)} unusual releases",
                    data={"unusual_titles": unusual_titles[:10]},
                )

        return SourcePayload(
            movies=movies,
            metadata={
                "notes": f"Loaded {len(movies)} movies from NZBGeek RSS",
                "rss_count": len(rows),
            },
        )

    @staticmethod
    def _requires_api_key(rss_url: str) -> bool:
        return "{API_KEY}" in rss_url or "${API_KEY}" in rss_url

    @staticmethod
    def _looks_unusual(parsed) -> bool:  # noqa: ANN001
        """Check if release has unusual/collector qualities."""
        return (
            parsed.is_criterion
            or parsed.is_remux
            or parsed.is_directors_cut
            or parsed.is_extended
            or parsed.is_hdr
        )
