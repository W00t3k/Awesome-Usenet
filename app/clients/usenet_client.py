from __future__ import annotations

from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
from xml.etree import ElementTree

from app.clients.http_client import HTTPClient


class UsenetClient:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: float):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http = HTTPClient(timeout_seconds)

    def _api_endpoint(self) -> str:
        if self._base_url.lower().endswith("/api"):
            return self._base_url
        return f"{self._base_url}/api"

    async def movie_search(self, query: str = "") -> list[dict]:
        params = {
            "apikey": self._api_key,
            "t": "search",
            "cat": "2000",  # Movies category (Newznab)
            "q": query,
            "o": "json",
            "limit": 100,
        }
        try:
            payload = await self._http.get_json(
                self._api_endpoint(),
                params=params,
            )
        except ValueError:
            xml_text = await self._http.get_text(self._api_endpoint(), params=params)
            return self._parse_rss_items(xml_text)

        items = payload.get("channel", {}).get("item", [])
        if isinstance(items, list):
            return items
        if isinstance(items, dict):
            return [items]
        return []

    async def movie_rss_feed(self, rss_url: str, api_key: str | None = None) -> list[dict]:
        resolved_url = self._resolve_rss_url(rss_url=rss_url, api_key=api_key or self._api_key)
        xml_text = await self._http.get_text(resolved_url)
        return self._parse_rss_items(xml_text)

    @staticmethod
    def _resolve_rss_url(rss_url: str, api_key: str | None) -> str:
        url = rss_url.strip()
        if api_key:
            url = url.replace("{API_KEY}", api_key)
            url = url.replace("${API_KEY}", api_key)

            # If the URL does not include an API key placeholder, add it as query.
            if "{API_KEY}" not in rss_url and "${API_KEY}" not in rss_url:
                parsed = urlparse(url)
                query = dict(parse_qsl(parsed.query, keep_blank_values=True))
                query.setdefault("apikey", api_key)
                url = urlunparse(
                    parsed._replace(query=urlencode(query, doseq=True))
                )

        return url

    @staticmethod
    def _parse_rss_items(xml_text: str) -> list[dict]:
        root = ElementTree.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            raise ValueError("Invalid RSS payload: missing channel node")

        items: list[dict] = []
        for item in channel.findall("item"):
            title = item.findtext("title", default="").strip()
            if not title:
                continue
            items.append(
                {
                    "title": title,
                    "link": item.findtext("link", default="").strip() or None,
                    "pub_date": item.findtext("pubDate", default="").strip() or None,
                    "description": item.findtext("description", default="").strip() or None,
                }
            )
        return items
