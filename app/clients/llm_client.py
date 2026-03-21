"""
Unified LLM client - supports Groq (cloud) and Ollama (local).

Groq: Fast cloud inference, free tier available
Ollama: Local inference, no API costs
"""

from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    """Protocol for LLM clients."""

    async def generate(self, prompt: str, system: str | None = None) -> str: ...


class UnifiedLLMClient:
    """LLM client supporting Groq (cloud) and Ollama (local)."""

    def __init__(
        self,
        groq_api_key: str | None = None,
        groq_model: str = "llama-3.3-70b-versatile",
        ollama_base_url: str | None = None,
        ollama_model: str = "llama3.2:1b",
        prefer_provider: str | None = None,  # "groq", "ollama", or None (auto)
    ):
        self._groq_client = None
        self._ollama_client = None
        self._active_client: str = "none"
        self._prefer_provider = prefer_provider

        # Initialize Groq client
        if groq_api_key:
            try:
                from app.clients.groq_client import GroqClient
                self._groq_client = GroqClient(api_key=groq_api_key, model=groq_model)
            except Exception:
                pass

        # Initialize Ollama client
        if ollama_base_url:
            try:
                from app.clients.ollama_client import OllamaClient
                self._ollama_client = OllamaClient(
                    base_url=ollama_base_url,
                    model=ollama_model,
                    timeout_seconds=60.0,
                )
            except Exception:
                pass

        # Set active client based on preference
        self._active_client = self._determine_active_client()

    def _determine_active_client(self) -> str:
        pref = self._prefer_provider
        if pref == "ollama" and self._ollama_client:
            return "ollama"
        elif pref == "groq" and self._groq_client:
            return "groq"
        elif self._groq_client:
            return "groq"
        elif self._ollama_client:
            return "ollama"
        return "none"

    @property
    def available(self) -> bool:
        return self._groq_client is not None or self._ollama_client is not None

    @property
    def provider(self) -> str:
        return self._active_client

    @property
    def groq_available(self) -> bool:
        return self._groq_client is not None

    @property
    def ollama_available(self) -> bool:
        return self._ollama_client is not None

    def get_available_providers(self) -> list[str]:
        providers = []
        if self._groq_client:
            providers.append("groq")
        if self._ollama_client:
            providers.append("ollama")
        return providers

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 500,
    ) -> str:
        """Generate text using the preferred LLM provider."""
        pref = self._prefer_provider

        if pref == "ollama":
            clients = [
                ("ollama", self._ollama_client),
                ("groq", self._groq_client),
            ]
        else:
            clients = [
                ("groq", self._groq_client),
                ("ollama", self._ollama_client),
            ]

        for name, client in clients:
            if not client:
                continue
            try:
                if name == "ollama":
                    result = await client.generate(prompt=prompt, system=system)
                else:
                    result = await client.generate(
                        prompt=prompt, system=system, max_tokens=max_tokens
                    )
                if result:
                    return result
            except Exception:
                continue

        return ""
