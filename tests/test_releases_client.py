import pytest

from app.clients.releases_client import ReleasesClient


def _movie_jsonld_html(title: str = "Example Movie") -> str:
    return f"""
    <html>
      <head>
        <script type="application/ld+json">
          {{
            "@context": "https://schema.org",
            "@type": "ItemList",
            "itemListElement": [
              {{
                "@type": "Movie",
                "name": "{title}",
                "datePublished": "2026-01-15",
                "position": 1
              }}
            ]
          }}
        </script>
      </head>
      <body></body>
    </html>
    """


def _cloudflare_html() -> str:
    return """
    <!DOCTYPE html>
    <html><head><title>Just a moment...</title></head>
    <body>
      <script>
        window._cf_chl_opt = {};
      </script>
      <script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1"></script>
    </body></html>
    """


def test_candidate_urls_include_movie_fallback_paths() -> None:
    urls = ReleasesClient._candidate_urls("https://www.releases.com/calendar/movie")
    assert urls == [
        "https://www.releases.com/calendar/movie",
        "https://www.releases.com/calendar/movies/upcoming",
        "https://www.releases.com/calendar/movies/new",
    ]


@pytest.mark.asyncio
async def test_upcoming_movies_falls_back_when_primary_path_fails() -> None:
    client = ReleasesClient(timeout_seconds=0.1)
    calls: list[str] = []

    async def fake_get_text(url: str, headers: dict | None = None) -> str:
        calls.append(url)
        if url.endswith("/calendar/movie"):
            raise RuntimeError("primary failed")
        return _movie_jsonld_html("Fallback Hit")

    client._http.get_text = fake_get_text  # type: ignore[method-assign]

    rows = await client.upcoming_movies("https://www.releases.com/calendar/movie")
    assert rows
    assert rows[0]["title"] == "Fallback Hit"
    assert calls[0].endswith("/calendar/movie")
    assert any(call.endswith("/calendar/movies/upcoming") for call in calls)


@pytest.mark.asyncio
async def test_upcoming_movies_reports_cloudflare_block() -> None:
    client = ReleasesClient(timeout_seconds=0.1)

    async def fake_get_text(url: str, headers: dict | None = None) -> str:
        _ = headers
        _ = url
        return _cloudflare_html()

    client._http.get_text = fake_get_text  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="blocked by Cloudflare challenge"):
        await client.upcoming_movies("https://www.releases.com/calendar/movie")
