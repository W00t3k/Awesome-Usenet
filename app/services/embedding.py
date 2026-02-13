from __future__ import annotations

import hashlib
import math
import re
from typing import Sequence

import numpy as np
from openai import AsyncOpenAI


class EmbeddingService:
    def __init__(
        self,
        openai_api_key: str | None,
        openai_model: str,
        dim: int = 384,
    ):
        self._client = AsyncOpenAI(api_key=openai_api_key) if openai_api_key else None
        self._model = openai_model
        self._dim = dim

    async def embed(self, text: str) -> list[float]:
        cleaned = text.strip()
        if not cleaned:
            return [0.0] * self._dim

        if self._client:
            response = await self._client.embeddings.create(model=self._model, input=cleaned)
            vector = response.data[0].embedding
            return vector

        return self._local_hash_embedding(cleaned)

    def _local_hash_embedding(self, text: str) -> list[float]:
        tokens = re.findall(r"[a-z0-9']+", text.lower())
        vec = np.zeros(self._dim, dtype=np.float32)
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            idx = int(digest[:8], 16) % self._dim
            sign = -1.0 if int(digest[8:9], 16) % 2 else 1.0
            vec[idx] += sign

        norm = math.sqrt(float(np.dot(vec, vec)))
        if norm == 0.0:
            return vec.tolist()
        return (vec / norm).tolist()

    @staticmethod
    def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
        if not a or not b:
            return 0.0
        if len(a) != len(b):
            return 0.0
        num = sum(x * y for x, y in zip(a, b, strict=False))
        den_a = math.sqrt(sum(x * x for x in a))
        den_b = math.sqrt(sum(y * y for y in b))
        if den_a == 0.0 or den_b == 0.0:
            return 0.0
        return num / (den_a * den_b)
