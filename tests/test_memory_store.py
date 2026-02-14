from pathlib import Path

import pytest

from app.models import FeedbackInput, SeenMovieInput
from app.services.embedding import EmbeddingService
from app.services.memory_store import MemoryStore


@pytest.mark.asyncio
async def test_memory_store_round_trip(tmp_path: Path) -> None:
    emb = EmbeddingService()
    store = MemoryStore(db_path=tmp_path / "memory.sqlite", embedding_service=emb)

    await store.add_feedback(
        FeedbackInput(
            user_id="u1",
            movie_id="m1",
            title="Seven Samurai",
            liked=True,
            genres=["Action", "Drama"],
            overview="A band of samurai defend a village",
        )
    )

    rows = store.recent_feedback("u1")
    assert len(rows) == 1
    assert rows[0].title == "Seven Samurai"

    score, nearest = await store.preference_similarity(
        user_id="u1",
        title="Seven Samurai",
        overview="Samurai protect villagers",
        genres=["Action"],
    )
    assert score > 0.4
    assert nearest

    rag_score, rag_nearest = await store.liked_rag_similarity(
        user_id="u1",
        title="Seven Samurai",
        overview="Samurai protect a farming village from raiders",
        genres=["Action"],
    )
    assert rag_score > 0.3
    assert rag_nearest


def test_seen_inventory_round_trip(tmp_path: Path) -> None:
    emb = EmbeddingService()
    store = MemoryStore(db_path=tmp_path / "memory.sqlite", embedding_service=emb)

    store.upsert_seen(
        SeenMovieInput(
            user_id="u1",
            movie_id="manual:arrival::2016",
            title="Arrival",
            year=2016,
            source="manual",
        )
    )

    keys = store.seen_title_keys("u1")
    assert "arrival::2016" in keys

    rows = store.list_seen("u1")
    assert len(rows) == 1
    assert rows[0].title == "Arrival"

    removed = store.remove_seen("u1", "manual:arrival::2016")
    assert removed is True
    assert store.list_seen("u1") == []
