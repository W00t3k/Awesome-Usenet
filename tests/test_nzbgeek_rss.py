import pytest

from app.agents.usenet_agent import UsenetAgent
from app.clients.usenet_client import UsenetClient
from app.models import AgentContext


def _context() -> AgentContext:
    return AgentContext(user_id="u1", requested_count=8, now_iso="2026-02-13T00:00:00+00:00")


def test_parse_rss_items_extracts_expected_fields() -> None:
    xml = """
    <rss version="2.0">
      <channel>
        <title>NZBGeek Movies</title>
        <item>
          <title>Dune.Part.Two.2024.1080p.BluRay.x265</title>
          <link>https://api.nzbgeek.info/details/abc</link>
          <pubDate>Fri, 13 Feb 2026 10:00:00 +0000</pubDate>
          <description>Example item</description>
        </item>
      </channel>
    </rss>
    """
    rows = UsenetClient._parse_rss_items(xml)

    assert len(rows) == 1
    assert rows[0]["title"].startswith("Dune.Part.Two")
    assert rows[0]["link"] == "https://api.nzbgeek.info/details/abc"


@pytest.mark.asyncio
async def test_usenet_client_avoids_double_api_suffix() -> None:
    client = UsenetClient(base_url="https://drunkenslug.com/api", api_key="k", timeout_seconds=0.1)
    seen: dict[str, str] = {}

    async def fake_get_json(url: str, params: dict | None = None, headers: dict | None = None) -> dict:
        seen["url"] = url
        return {"channel": {"item": []}}

    client._http.get_json = fake_get_json  # type: ignore[method-assign]
    await client.movie_search(query="")

    assert seen["url"] == "https://drunkenslug.com/api"


@pytest.mark.asyncio
async def test_nzbgeek_agent_collects_movie_candidates() -> None:
    agent = UsenetAgent(
        rss_url="https://api.nzbgeek.info/rss?t=search&cat=2000&apikey={API_KEY}",
        api_key="test-key",
        timeout_seconds=0.1,
    )

    async def fake_feed(_rss_url: str, api_key: str | None = None) -> list[dict]:
        assert api_key == "test-key"
        return [
            {
                "title": "The.Matrix.1999.1080p.BluRay.x264",
                "description": "Classic sci-fi",
                "pub_date": "Fri, 13 Feb 2026 11:00:00 +0000",
            }
        ]

    agent._client.movie_rss_feed = fake_feed  # type: ignore[method-assign]

    payload = await agent.collect(_context())
    assert payload.movies
    assert payload.movies[0].title == "The Matrix"
    assert payload.movies[0].year == 1999
    assert "nzbgeek-rss" in payload.movies[0].source_tags
