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

    @staticmethod
    def _extract_model_names(models: list[dict]) -> list[str]:
        names: list[str] = []
        for model in models:
            name = str(model.get("name") or model.get("model") or "").strip()
            if name and name not in names:
                names.append(name)
        return names

    @staticmethod
    def _resolve_model_name(requested_model: str, available_models: list[str]) -> str | None:
        requested = str(requested_model or "").strip()
        if not requested:
            return None

        requested_lower = requested.lower()
        for name in available_models:
            if name.lower() == requested_lower:
                return name

        requested_base = requested_lower.split(":")[0]
        for name in available_models:
            if name.lower().split(":")[0] == requested_base:
                return name
        return None

    async def _installed_model_names(self, client: httpx.AsyncClient) -> list[str]:
        response = await client.get(f"{self._base_url}/api/tags")
        response.raise_for_status()
        payload = response.json()
        return self._extract_model_names(payload.get("models", []) or [])

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

            if response.status_code == 404:
                installed_models: list[str] = []
                try:
                    installed_models = await self._installed_model_names(client)
                    fallback_model = self._resolve_model_name(self._model, installed_models)
                    if fallback_model and fallback_model != self._model:
                        retry_body = {**body, "model": fallback_model}
                        retry_response = await client.post(
                            f"{self._base_url}/api/generate",
                            json=retry_body,
                        )
                        retry_response.raise_for_status()
                        payload = retry_response.json()
                        return payload.get("response", "")
                except Exception:
                    pass

                available_preview = ", ".join(installed_models[:5]) if installed_models else "none"
                return f"Model '{self._model}' not found. Installed: {available_preview}"

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
                installed_models: list[str] = []
                try:
                    installed_models = await self._installed_model_names(client)
                    fallback_model = self._resolve_model_name(self._model, installed_models)
                    if fallback_model and fallback_model != self._model:
                        retry_body = {**body, "model": fallback_model}
                        retry_response = await client.post(
                            f"{self._base_url}/api/chat",
                            json=retry_body,
                        )
                        retry_response.raise_for_status()
                        payload = retry_response.json()
                        return payload.get("message", {}).get("content", "")
                except Exception:
                    pass

                available_preview = ", ".join(installed_models[:5]) if installed_models else "none"
                return f"Model '{self._model}' not found. Installed: {available_preview}"

            response.raise_for_status()
            payload = response.json()
            return payload.get("message", {}).get("content", "")

    async def health_check(self) -> dict[str, Any]:
        try:
            models = await self.list_models()
            model_names = self._extract_model_names(models)
            matched_model = self._resolve_model_name(self._model, model_names)
            model_available = matched_model is not None
            return {
                "ok": True,
                "models_count": len(models),
                "model_names": model_names[:10],
                "requested_model": self._model,
                "model_available": model_available,
                "matched_model": matched_model,
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
