"""
Groq Cloud LLM client - fast inference with free tier models.

Groq offers blazing fast inference on open-source models.
Free tier: 14,400 requests/day, 30 requests/minute.

Available models (as of 2024):
- llama-3.3-70b-versatile: Best quality, 128k context
- llama-3.1-8b-instant: Fastest, great for quick responses
- llama-3.2-11b-vision-preview: Vision + text capabilities
- mixtral-8x7b-32768: Long context (32k), good reasoning
- gemma2-9b-it: Google's efficient model
"""

from __future__ import annotations

import os
from groq import AsyncGroq


# Available Groq models with metadata
GROQ_MODELS = [
    {
        "id": "llama-3.3-70b-versatile",
        "name": "Llama 3.3 70B",
        "description": "Best quality, recommended for complex tasks",
        "context": 128000,
        "speed": "fast",
    },
    {
        "id": "llama-3.1-8b-instant",
        "name": "Llama 3.1 8B Instant",
        "description": "Fastest responses, great for simple tasks",
        "context": 128000,
        "speed": "instant",
    },
    {
        "id": "llama-3.2-11b-vision-preview",
        "name": "Llama 3.2 11B Vision",
        "description": "Vision + text, can analyze images",
        "context": 128000,
        "speed": "fast",
    },
    {
        "id": "mixtral-8x7b-32768",
        "name": "Mixtral 8x7B",
        "description": "Strong reasoning, 32k context",
        "context": 32768,
        "speed": "fast",
    },
    {
        "id": "gemma2-9b-it",
        "name": "Gemma 2 9B",
        "description": "Google's efficient instruction-tuned model",
        "context": 8192,
        "speed": "fast",
    },
]


GROQ_API_BASE = "https://api.groq.com"


class GroqClient:
    """Async client for Groq Cloud LLM API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "llama-3.3-70b-versatile",
    ):
        self._api_key = api_key or os.getenv("GROQ_API_KEY")
        self._model = model
        self._client = AsyncGroq(api_key=self._api_key, base_url=GROQ_API_BASE) if self._api_key else None

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def model(self) -> str:
        return self._model

    @staticmethod
    def get_available_models() -> list[dict]:
        """Return list of available Groq models with metadata."""
        return GROQ_MODELS.copy()

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 500,
        temperature: float = 0.7,
        raise_on_error: bool = False,
    ) -> str:
        """Generate text using Groq Cloud (fast!)."""
        if not self._client:
            if raise_on_error:
                raise RuntimeError("Groq client not initialized - missing API key")
            return ""

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            if raise_on_error:
                raise
            print(f"Groq error: {e}")
            return ""

    async def generate_batch(
        self,
        prompts: list[str],
        system: str | None = None,
        max_tokens: int = 150,
    ) -> list[str]:
        """Generate multiple responses efficiently."""
        import asyncio
        tasks = [
            self.generate(prompt, system=system, max_tokens=max_tokens)
            for prompt in prompts
        ]
        return await asyncio.gather(*tasks)

    async def test_connection(self) -> tuple[bool, str]:
        """Test the Groq connection and return status."""
        if not self._client:
            return False, "No API key configured"

        # Validate model name
        valid_model_ids = [m["id"] for m in GROQ_MODELS]
        if self._model not in valid_model_ids:
            return False, f"Invalid model '{self._model}'. Valid: {', '.join(valid_model_ids)}"

        try:
            result = await self.generate("Say 'ok' in one word.", max_tokens=10, raise_on_error=True)
            if result and result.strip():
                return True, f"Connected (model: {self._model})"
            return False, f"Empty response from model {self._model} - model may not support text-only prompts"
        except Exception as e:
            error_msg = str(e)
            # Extract useful info from Groq API errors
            if "invalid_api_key" in error_msg.lower() or "authentication" in error_msg.lower():
                return False, "Invalid API key"
            if "model" in error_msg.lower() or "not found" in error_msg.lower():
                return False, f"Model error: {error_msg}"
            if "rate" in error_msg.lower() or "limit" in error_msg.lower():
                return False, f"Rate limited: {error_msg}"
            return False, f"API error: {error_msg}"
