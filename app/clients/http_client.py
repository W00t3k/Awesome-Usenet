from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Phase 4: Global shared HTTP client with connection pooling
_shared_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()


async def get_shared_client() -> httpx.AsyncClient:
    """Get or create a shared HTTP client with connection pooling."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        async with _client_lock:
            # Double-check after acquiring lock
            if _shared_client is None or _shared_client.is_closed:
                _shared_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(10.0),
                    limits=httpx.Limits(
                        max_connections=100,
                        max_keepalive_connections=20,
                        keepalive_expiry=30.0,
                    ),
                    follow_redirects=True,
                )
                logger.info("Created shared HTTP client with connection pooling")
    return _shared_client


async def close_shared_client() -> None:
    """Close the shared HTTP client (call on app shutdown)."""
    global _shared_client
    if _shared_client is not None:
        await _shared_client.aclose()
        _shared_client = None
        logger.info("Closed shared HTTP client")


class HTTPClient:
    """HTTP client that uses connection pooling via a shared client."""

    def __init__(self, timeout_seconds: float = 8.0, use_pooling: bool = True):
        self._timeout = httpx.Timeout(timeout_seconds)
        self._use_pooling = use_pooling

    async def _get_client(self) -> httpx.AsyncClient:
        """Get the appropriate client based on pooling setting."""
        if self._use_pooling:
            return await get_shared_client()
        # Create a new client for this request (legacy behavior)
        return httpx.AsyncClient(timeout=self._timeout)

    async def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        if self._use_pooling:
            client = await self._get_client()
            response = await client.get(url, params=params, headers=headers, timeout=self._timeout)
            response.raise_for_status()
            return response.json()
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                return response.json()

    async def get_text(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        if self._use_pooling:
            client = await self._get_client()
            response = await client.get(url, params=params, headers=headers, timeout=self._timeout)
            response.raise_for_status()
            return response.text
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                return response.text

    async def post_json(
        self,
        url: str,
        payload: dict[str, Any] | list[Any],
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        if self._use_pooling:
            client = await self._get_client()
            response = await client.post(url, params=params, headers=headers, json=payload, timeout=self._timeout)
            response.raise_for_status()
            return response.json()
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, params=params, headers=headers, json=payload)
                response.raise_for_status()
                return response.json()

    async def delete(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        if self._use_pooling:
            client = await self._get_client()
            response = await client.delete(url, params=params, headers=headers, timeout=self._timeout)
            response.raise_for_status()
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.delete(url, params=params, headers=headers)
                response.raise_for_status()
