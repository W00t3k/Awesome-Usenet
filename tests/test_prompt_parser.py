from datetime import datetime

from app.agents.prompt_parser import parse_prompt


def test_parse_prompt_extracts_runtime_genre_and_family() -> None:
    prefs = parse_prompt("Funny sci fi movie under 100 minutes for kids")

    assert prefs.max_runtime_minutes == 100
    assert prefs.family_only is True
    assert "sci-fi" in prefs.genres
    assert "funny" in prefs.moods


def test_parse_prompt_infers_recent() -> None:
    prefs = parse_prompt("Recent inspiring drama")

    assert "drama" in prefs.genres
    assert "inspiring" in prefs.moods
    assert prefs.min_year == datetime.now().year - 10
