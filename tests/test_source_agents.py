import json
from pathlib import Path

import pytest

from app.agents.criterion_agent import CriterionAgent
from app.agents.drunkenslug_agent import DrunkenSlugAgent
from app.agents.releases_agent import ReleasesAgent
from app.agents.rogerebert_agent import RogerEbertAgent
from app.agents.rottentomatoes_agent import RottenTomatoesAgent
from app.clients.rottentomatoes_client import RottenTomatoesClient
from app.models import AgentContext


def _context() -> AgentContext:
    return AgentContext(user_id="u1", requested_count=10, now_iso="2026-01-01T00:00:00+00:00")


@pytest.mark.asyncio
async def test_rottentomatoes_agent_uses_fallback_dataset(tmp_path: Path) -> None:
    dataset = [
        {
            "position": 1,
            "title": "Test Film",
            "year": 2025,
            "tomatometer": 97,
            "review_count": 120,
            "url": "https://www.rottentomatoes.com/m/test_film",
        }
    ]
    dataset_path = tmp_path / "rt_seed.json"
    dataset_path.write_text(json.dumps(dataset))

    agent = RottenTomatoesAgent(
        list_url=None,
        timeout_seconds=0.1,
        fallback_dataset_path=dataset_path,
    )

    payload = await agent.collect(_context())
    assert payload.movies
    assert payload.movies[0].title == "Test Film"
    assert "rottentomatoes" in payload.movies[0].source_tags
    assert "rt-95plus" in payload.movies[0].source_tags


@pytest.mark.asyncio
async def test_releases_agent_uses_fallback_dataset(tmp_path: Path) -> None:
    dataset = [
        {
            "position": 1,
            "title": "Future Film",
            "release_date": "2026-08-10",
            "year": 2026,
            "url": "https://www.releases.com/p/future-film",
        }
    ]
    dataset_path = tmp_path / "releases_seed.json"
    dataset_path.write_text(json.dumps(dataset))

    agent = ReleasesAgent(
        releases_url=None,
        timeout_seconds=0.1,
        fallback_dataset_path=dataset_path,
    )

    payload = await agent.collect(_context())
    assert payload.movies
    assert payload.movies[0].title == "Future Film"
    assert "releases" in payload.movies[0].source_tags
    assert payload.movies[0].release_date == "2026-08-10"


@pytest.mark.asyncio
async def test_rogerebert_agent_filters_to_2025_2026(tmp_path: Path) -> None:
    dataset = [
        {
            "title": "Past Review",
            "year": 2024,
            "release_date": "2024-07-10",
            "url": "https://www.rogerebert.com/reviews/past-review-2024",
            "rating": 3.0,
        },
        {
            "title": "Current Review",
            "year": 2025,
            "release_date": "2025-07-10",
            "url": "https://www.rogerebert.com/reviews/current-review-2025",
            "rating": 3.5,
        },
    ]
    dataset_path = tmp_path / "rogerebert_seed.json"
    dataset_path.write_text(json.dumps(dataset))

    agent = RogerEbertAgent(
        reviews_url=None,
        timeout_seconds=0.1,
        fallback_dataset_path=dataset_path,
    )
    payload = await agent.collect(_context())

    assert len(payload.movies) == 1
    assert payload.movies[0].title == "Current Review"
    assert payload.movies[0].year == 2025


def test_rottentomatoes_client_extracts_jsonld_movies() -> None:
    html = """
    <script type="application/ld+json">
      {"@context":"http://schema.org","@type":"ItemList","itemListElement":{"@type":"ItemList","itemListElement":[{"@type":"Movie","name":"Sample Movie","position":1,"dateCreated":"2025","aggregateRating":{"ratingValue":"96","reviewCount":210},"url":"https://www.rottentomatoes.com/m/sample_movie","image":"https://cdn.example.com/sample.jpg"}]}}
    </script>
    """
    payload = RottenTomatoesClient._extract_jsonld_payload(html)
    movies = RottenTomatoesClient._extract_movies(payload)

    assert len(movies) == 1
    assert movies[0]["title"] == "Sample Movie"
    assert movies[0]["tomatometer"] == 96
    assert movies[0]["image"] == "https://cdn.example.com/sample.jpg"


@pytest.mark.asyncio
async def test_criterion_agent_handles_numeric_spine_id(tmp_path: Path) -> None:
    dataset_path = tmp_path / "criterion.json"
    dataset_path.write_text(
        json.dumps([{"spine": 1017, "title": "Parasite", "year": 2019, "genres": ["Thriller"]}])
    )

    agent = CriterionAgent(dataset_path=dataset_path)
    payload = await agent.collect(_context())

    assert len(payload.movies) == 1
    assert payload.movies[0].movie_id == "criterion:1017"


@pytest.mark.asyncio
async def test_drunkenslug_agent_collects_movie_candidates() -> None:
    agent = DrunkenSlugAgent(
        base_url="https://api.drunkenslug.com",
        api_key="test-key",
        timeout_seconds=0.1,
    )

    async def fake_search(query: str = "") -> list[dict]:
        assert query == ""
        return [
            {
                "title": "The.Huckleberry.Hound.Show.S01E04.FLAC2.0.HDTV",
                "description": "Should be excluded",
                "link": "https://drunkenslug.com/details/skip",
            },
            {
                "title": "Anora.2025.1080p.BluRay.x265",
                "description": "Example DS item",
                "link": "https://drunkenslug.com/details/123",
                "pubDate": "Fri, 13 Feb 2026 12:00:00 +0000",
            }
        ]

    agent._client.movie_search = fake_search  # type: ignore[method-assign]

    payload = await agent.collect(_context())
    assert payload.movies
    assert len(payload.movies) == 1
    assert payload.movies[0].title == "Anora"
    assert payload.movies[0].year == 2025
    assert "drunkenslug" in payload.movies[0].source_tags
    assert any(e.startswith("DrunkenSlug item date:") for e in payload.movies[0].evidence)
