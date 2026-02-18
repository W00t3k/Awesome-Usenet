from __future__ import annotations

import asyncio
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from html import unescape
from typing import Any
from urllib.parse import urljoin

from app.clients.http_client import HTTPClient


class RogerEbertClient:
    BASE_URL = "https://www.rogerebert.com"
    RSS_REVIEWS_URL = "https://www.rogerebert.com/reviews/feed"

    # Browser-like headers to avoid 403 blocks
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }

    # RSS headers (more permissive)
    RSS_HEADERS = {
        "User-Agent": "Mozilla/5.0 (compatible; MajicMovieSelector/1.0)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }

    def __init__(self, timeout_seconds: float):
        self._http = HTTPClient(timeout_seconds)

    async def recent_reviews(self, reviews_url: str, limit: int = 24) -> list[dict[str, Any]]:
        """Fetch recent reviews from a single page."""
        return await self._fetch_reviews_from_page(reviews_url, limit)

    async def reviews_from_rss(self, years: set[int] | None = None) -> list[dict[str, Any]]:
        """Fetch movie reviews from the RSS feed (more reliable than web scraping)."""
        try:
            xml_text = await self._http.get_text(self.RSS_REVIEWS_URL, headers=self.RSS_HEADERS)
            return self._parse_rss_feed(xml_text, years)
        except Exception:  # noqa: BLE001
            return []

    def _parse_rss_feed(self, xml_text: str, years: set[int] | None = None) -> list[dict[str, Any]]:
        """Parse RSS feed XML and extract movie reviews."""
        reviews: list[dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []

        # Find all <item> elements (RSS format)
        for item in root.iter("item"):
            title_elem = item.find("title")
            link_elem = item.find("link")
            pub_date_elem = item.find("pubDate")

            if title_elem is None or link_elem is None:
                continue

            raw_title = title_elem.text or ""
            url = link_elem.text or ""
            pub_date = pub_date_elem.text if pub_date_elem is not None else None

            # Skip non-review URLs (Great Movies, etc.)
            if "/reviews/great-movie" in url.lower():
                continue

            # Extract year from URL (e.g., "movie-review-2026")
            year = self._extract_year_from_url(url)

            # Filter by years if specified
            if years and year not in years:
                continue

            # Clean up title (remove year suffix if present)
            title = self._clean_rss_title(raw_title)
            if not title:
                continue

            # Parse publication date
            release_date = self._parse_rss_date(pub_date)

            reviews.append({
                "title": title,
                "year": year,
                "release_date": release_date,
                "url": url,
                "image": None,  # RSS doesn't include poster images
                "rating": None,  # Would need to scrape individual pages for rating
            })

        return reviews

    @staticmethod
    def _extract_year_from_url(url: str) -> int | None:
        """Extract year from RogerEbert URL like 'movie-review-2026'."""
        match = re.search(r"-(\d{4})$", url.rstrip("/"))
        if match:
            return int(match.group(1))
        # Try to find year anywhere in URL
        match = re.search(r"(202[456])(?![0-9])", url)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _clean_rss_title(title: str) -> str:
        """Clean up RSS title, removing year suffixes and common prefixes."""
        # Unescape HTML entities
        title = unescape(title).strip()
        # Remove review suffix patterns
        title = re.sub(r"\s*\(?\d{4}\)?$", "", title).strip()
        return title

    @staticmethod
    def _parse_rss_date(date_str: str | None) -> str | None:
        """Parse RSS pubDate format (RFC 2822) to ISO date."""
        if not date_str:
            return None
        try:
            # RFC 2822 format: "Tue, 17 Feb 2026 21:37:18 +0000"
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_str)
            return dt.date().isoformat()
        except Exception:  # noqa: BLE001
            # Fallback: try to extract date
            match = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", date_str)
            if match:
                day, month_str, year = match.groups()
                months = {
                    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
                    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
                    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
                }
                month = months.get(month_str[:3], "01")
                return f"{year}-{month}-{day.zfill(2)}"
        return None

    async def all_reviews_for_years(
        self,
        base_url: str,
        years: set[int],
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Fetch ALL reviews for specific years by paginating through the reviews.
        Stops when we hit reviews older than our target years.
        """
        all_reviews: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        min_year = min(years)

        for page in range(1, max_pages + 1):
            # RogerEbert uses ?page=N for pagination
            page_url = f"{base_url}?page={page}" if page > 1 else base_url

            try:
                reviews = await self._fetch_reviews_from_page(page_url, limit=50)
            except Exception:  # noqa: BLE001
                break

            if not reviews:
                break

            new_reviews = 0
            oldest_year_on_page = 9999

            for review in reviews:
                url = review.get("url", "")
                year = review.get("year")

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                if isinstance(year, int):
                    oldest_year_on_page = min(oldest_year_on_page, year)
                    if year in years:
                        all_reviews.append(review)
                        new_reviews += 1

            # Stop if we've gone past our target years
            if oldest_year_on_page < min_year:
                break

            # Stop if this page had no new reviews for our years
            if new_reviews == 0 and oldest_year_on_page < min_year:
                break

            # Small delay between pages to be polite
            await asyncio.sleep(0.5)

        return all_reviews

    async def _fetch_reviews_from_page(self, page_url: str, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch reviews from a single page."""
        html = await self._http.get_text(page_url, headers=self.HEADERS)
        links = self._extract_review_links(html)
        if not links:
            return []

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
                    article_html = await self._http.get_text(link, headers=self.HEADERS)
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
