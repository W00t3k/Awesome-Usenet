from __future__ import annotations

from app.agents.base import MovieAgent
from app.models import AgentContext, SourcePayload
from app.services.memory_store import MemoryStore


class PreferenceAgent(MovieAgent):
    name = "preferences"

    def __init__(self, memory_store: MemoryStore):
        self._memory_store = memory_store

    async def collect(self, context: AgentContext) -> SourcePayload:
        rows = self._memory_store.recent_feedback(context.user_id, limit=50)
        liked = sum(1 for row in rows if row.liked)
        disliked = len(rows) - liked
        return SourcePayload(
            metadata={
                "feedback_count": len(rows),
                "liked_count": liked,
                "disliked_count": disliked,
                "notes": "Preference memory loaded",
            }
        )
