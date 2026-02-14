from __future__ import annotations

import hashlib
import re

from app.agents.base import MovieAgent
from app.clients.usenet_client import UsenetClient
from app.models import AgentContext, MovieCandidate, SourcePayload


class UsenetAgent(MovieAgent):
    name = "nzbgeek"

    def __init__(self, rss_url: str | None, api_key: str | None, timeout_seconds: float):
        self._rss_url = rss_url
        self._api_key = api_key
        # base_url is not used for RSS mode; keep a harmless default for client construction.
        self._client = UsenetClient(base_url="https://api.nzbgeek.info", api_key=api_key or "", timeout_seconds=timeout_seconds)

    async def collect(self, context: AgentContext) -> SourcePayload:
        if not self._rss_url:
            return SourcePayload(metadata={"notes": "NZBGEEK_RSS_URL missing; skipping NZBGeek RSS"})
        if self._requires_api_key(self._rss_url) and not self._api_key:
            return SourcePayload(
                metadata={"notes": "NZBGEEK_API_KEY missing for RSS URL template; skipping NZBGeek RSS"}
            )

        rows = await self._client.movie_rss_feed(self._rss_url, api_key=self._api_key)
        movies: list[MovieCandidate] = []
        for row in rows:
            raw_title = (row.get("title") or "").strip()
            if not raw_title:
                continue

            title, year = self._extract_title_year(raw_title)
            tags = ["nzbgeek", "usenet", "nzbgeek-rss"]
            if self._looks_unusual(raw_title):
                tags.append("unusual-discovery")

            evidence = ["NZBGeek RSS release listing"]
            if row.get("pub_date"):
                evidence = [f"NZBGeek RSS item: {row['pub_date']}"]

            movies.append(
                MovieCandidate(
                    movie_id=f"nzbgeek:{hashlib.sha1(raw_title.encode('utf-8')).hexdigest()[:12]}",
                    title=title,
                    year=year,
                    overview=row.get("description"),
                    source_tags=tags,
                    evidence=evidence,
                    available_on_usenet=True,
                )
            )

        return SourcePayload(
            movies=movies,
            metadata={"notes": f"Loaded {len(movies)} candidates from NZBGeek RSS"},
        )

    @staticmethod
    def _requires_api_key(rss_url: str) -> bool:
        return "{API_KEY}" in rss_url or "${API_KEY}" in rss_url

    @staticmethod
    def _extract_title_year(raw_title: str) -> tuple[str, int | None]:
        # Strip common release suffix noise: quality, codec, scene tags, etc.
        compact = re.sub(r"[._]", " ", raw_title)
        compact = re.sub(
            r"\b(2160p|1080p|720p|x264|x265|h264|h265|hevc|hdr|webrip|web-dl|bluray|brrip|dvdrip|aac|dts|atmos|proper|repack|extended|criterion)\b",
            "",
            compact,
            flags=re.IGNORECASE,
        )
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", compact)
        year = int(year_match.group(1)) if year_match else None

        # Keep portion before year for cleaner movie title.
        if year_match:
            title = compact[: year_match.start()].strip(" -:[]()")
        else:
            title = compact

        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            title = raw_title
        return title, year

    @staticmethod
    def _looks_unusual(title: str) -> bool:
        lowered = title.lower()
        return any(
            marker in lowered
            for marker in [
                "restored",
                "criterion",
                "director's cut",
                "rare",
                "unrated",
                "remux",
            ]
        )
