from app.clients.rogerebert_client import RogerEbertClient


def test_extract_review_links_collects_review_paths() -> None:
    html = """
    <a href="/reviews/the-brutalist-2025">The Brutalist</a>
    <a href="/reviews/mickey-17-2025">Mickey 17</a>
    <a href="/interviews/some-director">Interview</a>
    """
    links = RogerEbertClient._extract_review_links(html)
    assert len(links) == 2
    assert links[0] == "https://www.rogerebert.com/reviews/the-brutalist-2025"


def test_extract_review_parses_date_year_and_rating() -> None:
    html = """
    <meta property="article:published_time" content="2025-03-07T12:00:00Z" />
    <meta property="og:image" content="https://img.example/poster.jpg" />
    <h1>Mickey 17 (2025)</h1>
    <script type="application/ld+json">
      {"@type":"Review","datePublished":"2025-03-07","reviewRating":{"ratingValue":"3.5"}}
    </script>
    """
    row = RogerEbertClient._extract_review(
        html, "https://www.rogerebert.com/reviews/mickey-17-2025"
    )
    assert row is not None
    assert row["title"] == "Mickey 17 (2025)"
    assert row["release_date"] == "2025-03-07"
    assert row["year"] == 2025
    assert row["rating"] == 3.5
