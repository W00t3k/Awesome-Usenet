from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from html import unescape
from typing import Any
from urllib.parse import urljoin

from app.clients.http_client import HTTPClient


class RogerEbertClient:
    BASE_URL = "https://www.rogerebert.com"

    def __init__(self, timeout_seconds: float):
        self._http = HTTPClient(timeout_seconds)

    async def recent_reviews(self, reviews_url: str, limit: int = 24) -> list[dict[str, Any]]:
        html = await self._http.get_text(
            reviews_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                )
            },
        )
        links = self._extract_review_links(html)
        if not links:
            raise ValueError("No review links found on RogerEbert page")

        unique_links: list[str] = []
        seen: set[str] = set()
        for link in links:
            if link in seen:
                continue
            seen.add(link)
            unique_links.append(link)
            if len(unique_links) >= limit:
                break

        semaphore = asyncio.Semaphore(4)

        async def _fetch_one(link: str) -> dict[str, Any] | None:
            async with semaphore:
                try:
                    article_html = await self._http.get_text(
                        link,
                        headers={
                            "User-Agent": (
                                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                            )
                        },
                    )
                    return self._extract_review(article_html, link)
                except Exception:  # noqa: BLE001
                    return None

        results = await asyncio.gather(*(_fetch_one(link) for link in unique_links))
        return [row for row in results if row is not None]

    @staticmethod
    def _extract_review_links(html: str) -> list[str]:
        raw_links = re.findall(r'href=["\'](/reviews/[^"\'#?]+)["\']', html, flags=re.IGNORECASE)
        links: list[str] = []
        for path in raw_links:
            normalized = path.rstrip("/")
            if normalized in {"/reviews", "/reviews/all"}:
                continue
            links.append(urljoin(RogerEbertClient.BASE_URL, normalized))
        return links

    @staticmethod
    def _extract_review(html: str, url: str) -> dict[str, Any] | None:
        title = RogerEbertClient._extract_title(html)
        if not title:
            return None

        published_iso = RogerEbertClient._extract_published_iso(html)
        year = RogerEbertClient._extract_year(html, title, published_iso)
        image = RogerEbertClient._extract_meta_content(html, "property", "og:image")
        rating = RogerEbertClient._extract_rating(html)

        return {
            "title": title,
            "year": year,
            "release_date": published_iso,
            "url": url,
            "image": image,
            "rating": rating,
        }

    @staticmethod
    def _extract_title(html: str) -> str | None:
        match = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        text = re.sub(r"<[^>]+>", "", match.group(1))
        cleaned = unescape(text).strip()
        return cleaned or None

    @staticmethod
    def _extract_published_iso(html: str) -> str | None:
        published = RogerEbertClient._extract_meta_content(html, "property", "article:published_time")
        if not published:
            published = RogerEbertClient._extract_jsonld_date_published(html)
        if not published:
            published = RogerEbertClient._extract_visible_date(html)
        return RogerEbertClient._coerce_iso_date(published)

    @staticmethod
    def _extract_jsonld_date_published(html: str) -> str | None:
        blocks = re.findall(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for block in blocks:
            text = block.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            date = RogerEbertClient._walk_for_key(payload, "datePublished")
            if isinstance(date, str) and date.strip():
                return date.strip()
        return None

    @staticmethod
    def _extract_rating(html: str) -> float | None:
        # Prefer JSON-LD rating values when available.
        blocks = re.findall(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for block in blocks:
            text = block.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            value = RogerEbertClient._walk_for_key(payload, "ratingValue")
            parsed = RogerEbertClient._as_float(value)
            if parsed is not None:
                return parsed

        # Fallback: plain-text mention like "3.5 stars out of 4".
        match = re.search(
            r"([0-4](?:\.\d+)?)\s+stars?\s+out\s+of\s+4",
            html,
            flags=re.IGNORECASE,
        )
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

    @staticmethod
    def _walk_for_key(node: Any, key: str) -> Any | None:
        if isinstance(node, dict):
            if key in node:
                return node[key]
            for value in node.values():
                found = RogerEbertClient._walk_for_key(value, key)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = RogerEbertClient._walk_for_key(item, key)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _extract_visible_date(html: str) -> str | None:
        # Example: "October 16, 1992"
        match = re.search(
            r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b",
            html,
            flags=re.IGNORECASE,
        )
        return match.group(0) if match else None

    @staticmethod
    def _extract_year(html: str, title: str, published_iso: str | None) -> int | None:
        title_year = re.search(r"\((19|20)\d{2}\)", title)
        if title_year:
            return int(title_year.group(0)[1:5])

        dot_year = re.search(r"[·‧]\s*((19|20)\d{2})", html)
        if dot_year:
            return int(dot_year.group(1))

        if published_iso:
            return int(published_iso[:4])
        return None

    @staticmethod
    def _extract_meta_content(html: str, attr_name: str, attr_value: str) -> str | None:
        pattern = (
            r"<meta[^>]*"
            + re.escape(attr_name)
            + r'=["\']'
            + re.escape(attr_value)
            + r'["\'][^>]*content=["\']([^"\']+)["\'][^>]*>'
        )
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return unescape(match.group(1)).strip()
        return None

    @staticmethod
    def _coerce_iso_date(raw: str | None) -> str | None:
        if not raw:
            return None
        text = raw.strip()
        if not text:
            return None

        # Full ISO datetime or date.
        try:
            if "T" in text:
                return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
            return datetime.fromisoformat(text).date().isoformat()
        except ValueError:
            pass

        for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue

        match = re.search(r"(19|20)\d{2}", text)
        if match:
            return f"{match.group(0)}-01-01"
        return None

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return float(text)
            except ValueError:
                return None
        return None
