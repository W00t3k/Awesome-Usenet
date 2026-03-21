from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from app.models import AgentContext, SourcePayload

if TYPE_CHECKING:
    from app.services.swarm_context import SwarmContext


class MovieAgent(ABC):
    """
    Base class for all movie data collection agents.

    Agents can opt-in to LLM features by setting supports_llm = True.
    When enabled, the agent receives a SwarmContext with LLM access,
    user preferences, and collaboration capabilities.
    """

    goal: str = "Gather reliable movie candidates with evidence and metadata the swarm can reason over."
    name: str

    # Set to True to receive SwarmContext with LLM capabilities
    supports_llm: bool = False

    @abstractmethod
    async def collect(self, context: AgentContext | SwarmContext) -> SourcePayload:
        """
        Collect movie candidates from this agent's data source.

        Args:
            context: Either AgentContext (basic) or SwarmContext (LLM-enabled)
                     when supports_llm=True

        Returns:
            SourcePayload with movies and metadata
        """
        raise NotImplementedError
