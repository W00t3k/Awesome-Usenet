import pytest

from app.clients.radarr_client import RadarrClient


@pytest.mark.asyncio
async def test_existing_movie_without_file_requests_search() -> None:
    client = RadarrClient(base_url="http://radarr.local", api_key="k", timeout_seconds=0.1)
    search_calls: list[int] = []

    async def fake_movies() -> list[dict]:
        return [{"id": 42, "title": "Inception", "year": 2010, "hasFile": False}]

    async def fake_search(movie_id: int) -> dict:
        search_calls.append(movie_id)
        return {"state": "queued"}

    client.movies = fake_movies  # type: ignore[method-assign]
    client.search_movie = fake_search  # type: ignore[method-assign]

    result = await client.ensure_movie_wanted(title="Inception", year=2010)

    assert result["status"] == "queued"
    assert search_calls == [42]


@pytest.mark.asyncio
async def test_existing_movie_with_file_does_not_search() -> None:
    client = RadarrClient(base_url="http://radarr.local", api_key="k", timeout_seconds=0.1)

    async def fake_movies() -> list[dict]:
        return [{"id": 42, "title": "Inception", "year": 2010, "hasFile": True}]

    async def fake_search(_movie_id: int) -> dict:
        raise AssertionError("search should not run when movie file already exists")

    client.movies = fake_movies  # type: ignore[method-assign]
    client.search_movie = fake_search  # type: ignore[method-assign]

    result = await client.ensure_movie_wanted(title="Inception", year=2010)

    assert result["status"] == "exists"
    assert "downloaded" in result["message"].lower()
