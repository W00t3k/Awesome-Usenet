from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import AgentContext, SourcePayload


class MovieAgent(ABC):
    name: str

    @abstractmethod
    async def collect(self, context: AgentContext) -> SourcePayload:
        raise NotImplementedError
