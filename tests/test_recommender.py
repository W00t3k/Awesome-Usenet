from pathlib import Path

import pytest

from app.models import FeedbackInput, MovieCandidate, SeenMovieInput
from app.services.embedding import EmbeddingService
from app.services.memory_store import MemoryStore
from app.services.recommender import Recommender


@pytest.mark.asyncio
async def test_recommender_prefers_available_award_title(tmp_path: Path) -> None:
    emb = EmbeddingService()
    store = MemoryStore(db_path=tmp_path / "memory.sqlite", embedding_service=emb)
    rec = Recommender(memory_store=store)

    await store.add_feedback(
        FeedbackInput(
            user_id="u1",
            movie_id="m1",
            title="Parasite",
            liked=True,
            genres=["Thriller", "Drama"],
            overview="Class satire thriller in Seoul",
        )
    )

    results = await rec.rank(
        user_id="u1",
        source_movies={
            "oscars": [
                MovieCandidate(
                    movie_id="oscars:parasite",
                    title="Parasite",
                    year=2019,
                    source_tags=["oscars", "best-picture-winner"],
                    evidence=["Best Picture winner (2020)"],
                )
            ],
            "plex": [
                MovieCandidate(
                    movie_id="plex:1",
                    title="Parasite",
                    year=2019,
                    source_tags=["plex"],
                    evidence=["Already in Plex library"],
                    available_on_plex=True,
                )
            ],
            "upcoming": [
                MovieCandidate(
                    movie_id="u:1",
                    title="Unknown Future Film",
                    release_date="2030-01-01",
                    source_tags=["upcoming"],
                    evidence=["Upcoming release"],
                )
            ],
        },
        top_n=5,
    )

    assert results
    assert results[0].movie.title == "Parasite"


@pytest.mark.asyncio
async def test_recommender_includes_new_source_reasons(tmp_path: Path) -> None:
    emb = EmbeddingService()
    store = MemoryStore(db_path=tmp_path / "memory.sqlite", embedding_service=emb)
    rec = Recommender(memory_store=store)

    results = await rec.rank(
        user_id="u1",
        source_movies={
            "rottentomatoes": [
                MovieCandidate(
                    movie_id="rt:1",
                    title="Critics Darling",
                    year=2025,
                    source_tags=["rottentomatoes", "rt-95plus"],
                    evidence=["Rotten Tomatoes Tomatometer: 97% (120 reviews)"],
                )
            ],
            "releases": [
                MovieCandidate(
                    movie_id="rel:1",
                    title="Soon To Premiere",
                    year=2026,
                    release_date="2026-04-10",
                    source_tags=["releases"],
                    evidence=["Releases.com upcoming date: 2026-04-10"],
                )
            ],
        },
        top_n=5,
    )

    reasons = {
        reason.label
        for rec_result in results
        for reason in rec_result.reasons
    }
    assert "Critic rating" in reasons
    assert "Releases.com" in reasons


@pytest.mark.asyncio
async def test_recommender_excludes_seen_inventory_titles(tmp_path: Path) -> None:
    emb = EmbeddingService()
    store = MemoryStore(db_path=tmp_path / "memory.sqlite", embedding_service=emb)
    rec = Recommender(memory_store=store)

    store.upsert_seen(
        SeenMovieInput(
            user_id="u1",
            movie_id="manual:parasite::2019",
            title="Parasite",
            year=2019,
            source="manual",
        )
    )

    results = await rec.rank(
        user_id="u1",
        source_movies={
            "oscars": [
                MovieCandidate(
                    movie_id="oscars:parasite",
                    title="Parasite",
                    year=2019,
                    source_tags=["oscars", "best-picture-winner"],
                    evidence=["Best Picture winner"],
                ),
                MovieCandidate(
                    movie_id="oscars:moonlight",
                    title="Moonlight",
                    year=2016,
                    source_tags=["oscars", "best-picture-winner"],
                    evidence=["Best Picture winner"],
                ),
            ]
        },
        top_n=5,
    )

    titles = [row.movie.title for row in results]
    assert "Parasite" not in titles
    assert "Moonlight" in titles


@pytest.mark.asyncio
async def test_recommender_source_filter_limits_results(tmp_path: Path) -> None:
    emb = EmbeddingService()
    store = MemoryStore(db_path=tmp_path / "memory.sqlite", embedding_service=emb)
    rec = Recommender(memory_store=store)

    results = await rec.rank(
        user_id="u1",
        source_movies={
            "nzbgeek": [
                MovieCandidate(
                    movie_id="nzb:1",
                    title="Rare Find",
                    year=2025,
                    source_tags=["nzbgeek", "nzbgeek-rss"],
                )
            ],
            "rottentomatoes": [
                MovieCandidate(
                    movie_id="rt:1",
                    title="Critics Pick",
                    year=2025,
                    source_tags=["rottentomatoes", "rt-95plus"],
                    rottentomatoes_score=95,
                )
            ],
        },
        top_n=10,
        required_sources={"nzbgeek"},
    )

    titles = [row.movie.title for row in results]
    assert titles == ["Rare Find"]


@pytest.mark.asyncio
async def test_recommender_source_filter_supports_drunkenslug(tmp_path: Path) -> None:
    emb = EmbeddingService()
    store = MemoryStore(db_path=tmp_path / "memory.sqlite", embedding_service=emb)
    rec = Recommender(memory_store=store)

    results = await rec.rank(
        user_id="u1",
        source_movies={
            "drunkenslug": [
                MovieCandidate(
                    movie_id="ds:1",
                    title="Slug Drop",
                    year=2026,
                    source_tags=["drunkenslug"],
                    available_on_usenet=True,
                )
            ],
            "rottentomatoes": [
                MovieCandidate(
                    movie_id="rt:1",
                    title="Critics Pick",
                    year=2025,
                    source_tags=["rottentomatoes", "rt-95plus"],
                    rottentomatoes_score=95,
                )
            ],
        },
        top_n=10,
        required_sources={"drunkenslug"},
    )

    titles = [row.movie.title for row in results]
    assert titles == ["Slug Drop"]


@pytest.mark.asyncio
async def test_recommender_uses_rogerebert_when_rt_missing(tmp_path: Path) -> None:
    emb = EmbeddingService()
    store = MemoryStore(db_path=tmp_path / "memory.sqlite", embedding_service=emb)
    rec = Recommender(memory_store=store)

    results = await rec.rank(
        user_id="u1",
        source_movies={
            "rogerebert": [
                MovieCandidate(
                    movie_id="re:1",
                    title="Ebert Choice",
                    year=2026,
                    source_tags=["rogerebert", "critic-review"],
                    rogerebert_score=3.5,
                )
            ]
        },
        top_n=5,
    )

    assert results
    critic_reasons = [
        reason.detail for reason in results[0].reasons if reason.label == "Critic rating"
    ]
    assert critic_reasons
    assert "RogerEbert" in critic_reasons[0]


@pytest.mark.asyncio
async def test_recommender_filters_tv_episode_style_usenet_titles(tmp_path: Path) -> None:
    emb = EmbeddingService()
    store = MemoryStore(db_path=tmp_path / "memory.sqlite", embedding_service=emb)
    rec = Recommender(memory_store=store)

    results = await rec.rank(
        user_id="u1",
        source_movies={
            "nzbgeek": [
                MovieCandidate(
                    movie_id="nzb:tv1",
                    title="The One Show S2026E30",
                    source_tags=["nzbgeek", "nzbgeek-rss"],
                    available_on_usenet=True,
                ),
                MovieCandidate(
                    movie_id="nzb:movie1",
                    title="28 Years Later",
                    year=2025,
                    source_tags=["nzbgeek", "nzbgeek-rss"],
                    available_on_usenet=True,
                ),
            ],
        },
        top_n=10,
    )

    titles = [row.movie.title for row in results]
    assert "The One Show S2026E30" not in titles
    assert "28 Years Later" in titles
