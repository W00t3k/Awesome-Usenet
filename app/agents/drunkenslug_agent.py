from __future__ import annotations

import hashlib
import re

from app.agents.base import MovieAgent
from app.clients.usenet_client import UsenetClient
from app.models import AgentContext, MovieCandidate, SourcePayload


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

        rows = await self._client.movie_search(query="")
        movies: list[MovieCandidate] = []
        for row in rows:
            raw_title = str(row.get("title") or row.get("name") or "").strip()
            if not raw_title:
                continue

            title, year = self._extract_title_year(raw_title)
            detail_link = str(row.get("link") or row.get("guid") or "").strip()
            overview = str(row.get("description") or "").strip() or "DrunkenSlug movie release listing"

            evidence = ["DrunkenSlug index listing"]
            if detail_link:
                evidence = [f"DrunkenSlug item: {detail_link}"]

            movies.append(
                MovieCandidate(
                    movie_id=f"drunkenslug:{hashlib.sha1(raw_title.encode('utf-8')).hexdigest()[:12]}",
                    title=title,
                    year=year,
                    overview=overview,
                    source_tags=["drunkenslug"],
                    evidence=evidence,
                    available_on_usenet=True,
                )
            )

        # Keep set bounded; we only need enough rows for scoring/ranking.
        item_limit = max(100, context.requested_count * 10)
        return SourcePayload(
            movies=movies[:item_limit],
            metadata={"notes": f"Loaded {min(len(movies), item_limit)} candidates from DrunkenSlug"},
        )

    @staticmethod
    def _extract_title_year(raw_title: str) -> tuple[str, int | None]:
        compact = re.sub(r"[._]", " ", raw_title)
        compact = re.sub(
            r"\b(2160p|1080p|720p|x264|x265|h264|h265|hevc|hdr|webrip|web-dl|bluray|brrip|dvdrip|aac|dts|atmos|proper|repack|extended|criterion)\b",
            "",
            compact,
            flags=re.IGNORECASE,
        )
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", compact)
        year = int(year_match.group(1)) if year_match else None

        if year_match:
            title = compact[: year_match.start()].strip(" -:[]()")
        else:
            title = compact

        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            title = raw_title
        return title, year
