from __future__ import annotations

import hashlib

from app.agents.base import MovieAgent
from app.clients.usenet_client import UsenetClient
from app.models import AgentContext, MovieCandidate, SourcePayload
from app.services.usenet_parser import parse_release


class DrunkenSlugAgent(MovieAgent):
    name = "drunkenslug"

    def __init__(self, base_url: str, api_key: str | None, timeout_seconds: float):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = UsenetClient(
            base_url=self._base_url,
            api_key=api_key or "",
            timeout_seconds=timeout_seconds,
        )

    async def collect(self, context: AgentContext) -> SourcePayload:
        if not self._api_key:
            return SourcePayload(metadata={"notes": "DRUNKENSLUG_API_KEY missing; skipping DrunkenSlug"})

        # Fetch ALL releases with pagination (up to 1000)
        rows = await self._client.movie_search_all(query="", max_results=1000)
        movies: list[MovieCandidate] = []
        seen_titles: set[str] = set()

        for row in rows:
            raw_title = str(row.get("title") or row.get("name") or "").strip()
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

            detail_link = str(row.get("link") or row.get("guid") or "").strip()
            posted_at = str(
                row.get("pubDate")
                or row.get("pub_date")
                or row.get("posted")
                or row.get("usenetdate")
                or ""
            ).strip()
            overview = str(row.get("description") or "").strip() or "DrunkenSlug movie release listing"

            tags = ["drunkenslug", "usenet"]
            if parsed.quality != "unknown":
                tags.append(parsed.quality)
            if parsed.is_hdr:
                tags.append("hdr")
            if parsed.is_criterion:
                tags.append("criterion-release")

            evidence = ["DrunkenSlug index listing"]
            if detail_link:
                evidence = [f"DrunkenSlug item: {detail_link}"]
            if posted_at:
                evidence.append(f"DrunkenSlug item date: {posted_at}")

            # Include quality details
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
                    movie_id=f"drunkenslug:{hashlib.sha1(raw_title.encode('utf-8')).hexdigest()[:12]}",
                    title=parsed.title,
                    year=parsed.year,
                    overview=overview,
                    source_tags=tags,
                    evidence=evidence,
                    available_on_usenet=True,
                )
            )

        return SourcePayload(
            movies=movies,
            metadata={"notes": f"Loaded {len(movies)} unique movies from DrunkenSlug"},
        )
