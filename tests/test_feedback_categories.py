from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app, settings


def test_feedback_skip_records_skipped_category() -> None:
    client = TestClient(app)
    user_id = f"u-skip-{uuid4()}"

    response = client.post(
        "/api/feedback",
        json={
            "user_id": user_id,
            "movie_id": "movie:skip_case",
            "title": "Skip Case",
            "liked": False,
            "year": 2026,
            "genres": ["Drama"],
            "overview": "test",
        },
    )
    assert response.status_code == 200
    assert response.json()["seen_source"] == "skipped"

    seen_rows = client.get(f"/api/seen/{user_id}").json()
    row = next(item for item in seen_rows if item["movie_id"] == "movie:skip_case")
    assert row["source"] == "skipped"


def test_feedback_keep_records_watch_and_radarr_status(monkeypatch) -> None:
    client = TestClient(app)
    user_id = f"u-watch-{uuid4()}"
    monkeypatch.setattr(settings, "radarr_api_key", None)

    response = client.post(
        "/api/feedback",
        json={
            "user_id": user_id,
            "movie_id": "movie:watch_case",
            "title": "Watch Case",
            "liked": True,
            "year": 2025,
            "genres": ["Action"],
            "overview": "test",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["seen_source"] == "watch"
    assert "radarr" not in payload

    seen_rows = client.get(f"/api/seen/{user_id}").json()
    row = next(item for item in seen_rows if item["movie_id"] == "movie:watch_case")
    assert row["source"] == "watch"
