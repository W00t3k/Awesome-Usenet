from __future__ import annotations

from typing import Any

import httpx


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout_seconds: float = 60.0):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = httpx.Timeout(timeout_seconds)

    async def list_models(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(f"{self._base_url}/api/tags")
            response.raise_for_status()
            payload = response.json()
            return payload.get("models", [])

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        stream: bool = False,
    ) -> str:
        body: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "stream": stream,
        }
        if system:
            body["system"] = system

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._base_url}/api/generate", json=body)

            # If model not found, try to pull it first
            if response.status_code == 404:
                return f"Model '{self._model}' not found. Please run: ollama pull {self._model}"

            response.raise_for_status()
            payload = response.json()
            return payload.get("response", "")

    async def chat(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        stream: bool = False,
    ) -> str:
        msg_list = list(messages)
        if system:
            msg_list = [{"role": "system", "content": system}] + msg_list

        body: dict[str, Any] = {
            "model": self._model,
            "messages": msg_list,
            "stream": stream,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._base_url}/api/chat", json=body)

            if response.status_code == 404:
                return f"Model '{self._model}' not found. Please run: ollama pull {self._model}"

            response.raise_for_status()
            payload = response.json()
            return payload.get("message", {}).get("content", "")

    async def health_check(self) -> dict[str, Any]:
        try:
            models = await self.list_models()
            model_names = [m.get("name", "").split(":")[0] for m in models]
            base_model = self._model.split(":")[0]
            model_available = any(base_model in name for name in model_names)
            return {
                "ok": True,
                "models_count": len(models),
                "model_names": model_names[:10],
                "requested_model": self._model,
                "model_available": model_available,
            }
        except httpx.HTTPError as exc:
            return {
                "ok": False,
                "models_count": 0,
                "model_names": [],
                "requested_model": self._model,
                "model_available": False,
                "error": f"Cannot connect to Ollama: {exc}",
            }
        except Exception as exc:
            return {
                "ok": False,
                "models_count": 0,
                "model_names": [],
                "requested_model": self._model,
                "model_available": False,
                "error": str(exc),
            }
