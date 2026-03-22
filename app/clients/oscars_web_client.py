from __future__ import annotations

import html as html_lib
import re
from typing import Any

from app.clients.http_client import HTTPClient


class OscarsWebClient:
    """Best-effort Oscar winner scraper used when local Oscar data is missing."""

    BEST_PICTURE_URL = "https://en.wikipedia.org/wiki/Academy_Award_for_Best_Picture"
    BEST_ACTOR_URL = "https://en.wikipedia.org/wiki/Academy_Award_for_Best_Actor"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    def __init__(self, timeout_seconds: float = 8.0):
        self._http = HTTPClient(timeout_seconds)

    async def fetch_best_picture_rows(self, limit_years: int = 40) -> list[dict[str, Any]]:
        html = await self._http.get_text(self.BEST_PICTURE_URL, headers=self.HEADERS)
        rows = self._extract_best_picture_rows_from_html(html)
        if not rows:
            return []
        rows.sort(key=lambda row: int(row.get("year") or 0), reverse=True)
        return rows[:limit_years]

    async def fetch_best_actor_rows(self, limit_years: int = 40) -> list[dict[str, Any]]:
        html = await self._http.get_text(self.BEST_ACTOR_URL, headers=self.HEADERS)
        rows = self._extract_best_actor_rows_from_html(html)
        if not rows:
            return []
        rows.sort(key=lambda row: int(row.get("year") or 0), reverse=True)
        return rows[:limit_years]

    @staticmethod
    def _extract_best_picture_rows_from_html(html: str) -> list[dict[str, Any]]:
        extracted: list[dict[str, Any]] = []
        seen_years: set[int] = set()

        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.IGNORECASE | re.DOTALL):
            year = OscarsWebClient._extract_year(row)
            if year is None or year in seen_years:
                continue

            winner = OscarsWebClient._extract_bold_title(row)
            if not winner:
                continue

            nominees = OscarsWebClient._extract_nominees(row, winner=winner)
            extracted.append(
                {
                    "year": year,
                    "winner": winner,
                    "nominees": nominees,
                    "source": "wikipedia-web-fallback",
                }
            )
            seen_years.add(year)

        return extracted

    @staticmethod
    def _extract_best_actor_rows_from_html(html: str) -> list[dict[str, Any]]:
        extracted: list[dict[str, Any]] = []
        seen_years: set[int] = set()

        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.IGNORECASE | re.DOTALL):
            year = OscarsWebClient._extract_year(row)
            if year is None or year in seen_years:
                continue

            actor = OscarsWebClient._extract_bold_person(row)
            film = OscarsWebClient._extract_italic_title(row)
            if not actor or not film:
                continue

            extracted.append(
                {
                    "year": year,
                    "best_actor": actor,
                    "best_actor_film": film,
                    "source": "wikipedia-web-fallback",
                }
            )
            seen_years.add(year)

        return extracted

    @staticmethod
    def _extract_year(row_html: str) -> int | None:
        text = OscarsWebClient._clean_text(OscarsWebClient._strip_tags(row_html))
        for year_text in re.findall(r"\b(19\d{2}|20\d{2})\b", text):
            year = int(year_text)
            if 1927 <= year <= 2100:
                return year
        return None

    @staticmethod
    def _extract_bold_title(row_html: str) -> str | None:
        bold_segments = re.findall(
            r"<b[^>]*>(.*?)</b>",
            row_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for segment in bold_segments:
            text = OscarsWebClient._extract_link_or_text(segment)
            cleaned = OscarsWebClient._normalize_title(text)
            if cleaned and OscarsWebClient._looks_like_movie_title(cleaned):
                return cleaned
        return None

    @staticmethod
    def _extract_bold_person(row_html: str) -> str | None:
        bold_segments = re.findall(
            r"<b[^>]*>(.*?)</b>",
            row_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for segment in bold_segments:
            text = OscarsWebClient._extract_link_or_text(segment)
            cleaned = OscarsWebClient._clean_text(text)
            if not cleaned:
                continue
            if not cleaned.lower().startswith("academy award"):
                return cleaned
        return None

    @staticmethod
    def _extract_italic_title(row_html: str) -> str | None:
        italic_segments = re.findall(
            r"<i[^>]*>(.*?)</i>",
            row_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for segment in italic_segments:
            text = OscarsWebClient._extract_link_or_text(segment)
            cleaned = OscarsWebClient._normalize_title(text)
            if cleaned and OscarsWebClient._looks_like_movie_title(cleaned):
                return cleaned
        return None

    @staticmethod
    def _extract_nominees(row_html: str, winner: str) -> list[str]:
        nominees: list[str] = []
        winner_key = OscarsWebClient._title_key(winner)

        italic_segments = re.findall(
            r"<i[^>]*>(.*?)</i>",
            row_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for segment in italic_segments:
            text = OscarsWebClient._extract_link_or_text(segment)
            cleaned = OscarsWebClient._normalize_title(text)
            if not cleaned or OscarsWebClient._title_key(cleaned) == winner_key:
                continue
            if cleaned not in nominees:
                nominees.append(cleaned)

        return nominees

    @staticmethod
    def _extract_link_or_text(html_segment: str) -> str:
        link_match = re.search(
            r"<a[^>]*>(.*?)</a>",
            html_segment,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if link_match:
            return OscarsWebClient._strip_tags(link_match.group(1))
        return OscarsWebClient._strip_tags(html_segment)

    @staticmethod
    def _strip_tags(raw_html: str) -> str:
        return re.sub(r"<[^>]+>", " ", raw_html or "")

    @staticmethod
    def _clean_text(value: str) -> str:
        text = html_lib.unescape(value or "")
        text = re.sub(r"\[[^\]]+\]", "", text)
        text = text.replace("\xa0", " ")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _normalize_title(value: str) -> str:
        cleaned = OscarsWebClient._clean_text(value)
        cleaned = re.sub(r"^\W+|\W+$", "", cleaned)
        cleaned = cleaned.replace("’", "'")
        return cleaned

    @staticmethod
    def _title_key(title: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", title.lower())

    @staticmethod
    def _looks_like_movie_title(value: str) -> bool:
        if not value:
            return False
        if value.lower().startswith("academy award"):
            return False
        words = value.split()
        if len(words) > 12:
            return False
        return True
