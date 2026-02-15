from __future__ import annotations

import logging
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
from xml.etree import ElementTree

from app.clients.http_client import HTTPClient

logger = logging.getLogger(__name__)


class UsenetClient:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: float):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http = HTTPClient(timeout_seconds)

    def _api_endpoint(self) -> str:
        if self._base_url.lower().endswith("/api"):
            return self._base_url
        return f"{self._base_url}/api"

    def _search_endpoint_and_params(
        self, query: str = "", offset: int = 0, limit: int = 100
    ) -> tuple[str, dict[str, str | int]]:
        parsed = urlparse(self._base_url)
        base_params = dict(parse_qsl(parsed.query, keep_blank_values=True))

        # Strip query/fragment and normalize the API endpoint path.
        endpoint = urlunparse(parsed._replace(query="", fragment="")).rstrip("/")
        if not endpoint.lower().endswith("/api"):
            endpoint = f"{endpoint}/api"

        params: dict[str, str | int] = {
            "t": "search",
            "cat": "2000",  # Movies category (Newznab)
            "o": "json",
            "limit": limit,
            "offset": offset,
        }
        if query.strip():
            params["q"] = query.strip()
        if self._api_key:
            params["apikey"] = self._api_key

        # Preserve explicit query-string defaults from base_url (for providers that require them).
        params.update(base_params)

        # Explicit function arguments / configured key always win.
        if query.strip():
            params["q"] = query.strip()
        if self._api_key:
            params["apikey"] = self._api_key
        params["limit"] = limit
        params["offset"] = offset

        return endpoint, params

    async def movie_search(
        self, query: str = "", offset: int = 0, limit: int = 100
    ) -> list[dict]:
        endpoint, params = self._search_endpoint_and_params(
            query=query, offset=offset, limit=limit
        )
        try:
            payload = await self._http.get_json(
                endpoint,
                params=params,
            )
        except ValueError:
            xml_text = await self._http.get_text(endpoint, params=params)
            return self._parse_rss_items(xml_text)

        items = payload.get("channel", {}).get("item", [])
        if isinstance(items, list):
            return items
        if isinstance(items, dict):
            return [items]
        return []

    async def movie_search_all(
        self, query: str = "", max_results: int = 1000, batch_size: int = 100
    ) -> list[dict]:
        """Fetch ALL search results with pagination."""
        all_items: list[dict] = []
        offset = 0
        while len(all_items) < max_results:
            batch = await self.movie_search(query=query, offset=offset, limit=batch_size)
            if not batch:
                break
            all_items.extend(batch)
            if len(batch) < batch_size:
                break
            offset += batch_size
        return all_items[:max_results]

    async def movie_rss_feed(self, rss_url: str, api_key: str | None = None) -> list[dict]:
        resolved_url = self._resolve_rss_url(rss_url=rss_url, api_key=api_key or self._api_key)
        logger.info(f"Fetching RSS from: {resolved_url[:80]}...")
        xml_text = await self._http.get_text(resolved_url)
        logger.info(f"Received {len(xml_text)} bytes, starts with: {xml_text[:100]}")
        items = self._parse_rss_items(xml_text)
        logger.info(f"Parsed {len(items)} items from RSS")
        return items

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
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError as exc:
            # Some indexers return HTML error pages instead of XML
            raise ValueError(f"Invalid XML from indexer: {exc}") from exc

        channel = root.find("channel")
        if channel is None:
            # Try Newznab error response: <error code="..." description="..."/>
            error_el = root.find("error")
            if error_el is not None:
                code = error_el.get("code", "?")
                desc = error_el.get("description", "unknown error")
                raise ValueError(f"Indexer error {code}: {desc}")
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
