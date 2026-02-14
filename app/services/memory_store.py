from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.models import FeedbackInput, FeedbackRow, SeenMovieInput, SeenMovieRow
from app.services.embedding import EmbeddingService


@dataclass
class SimilarFeedback:
    title: str
    liked: bool
    similarity: float


class MemoryStore:
    def __init__(self, db_path: Path, embedding_service: EmbeddingService):
        self._db_path = db_path
        self._embedding_service = embedding_service
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    movie_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    liked INTEGER NOT NULL,
                    note TEXT,
                    genres_json TEXT,
                    year INTEGER,
                    overview TEXT,
                    embedding_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_feedback_user
                ON feedback(user_id, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    movie_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    title_key TEXT NOT NULL,
                    year INTEGER,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_seen_inventory_user_movie
                ON seen_inventory(user_id, movie_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_seen_inventory_user_key
                ON seen_inventory(user_id, title_key)
                """
            )

    async def add_feedback(self, payload: FeedbackInput) -> None:
        text = self._compose_embedding_text(payload.title, payload.overview, payload.genres)
        embedding = await self._embedding_service.embed(text)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO feedback
                (user_id, movie_id, title, liked, note, genres_json, year, overview, embedding_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.user_id,
                    payload.movie_id,
                    payload.title,
                    int(payload.liked),
                    payload.note,
                    json.dumps(payload.genres),
                    payload.year,
                    payload.overview,
                    json.dumps(embedding),
                ),
            )

    def recent_feedback(self, user_id: str, limit: int = 100) -> list[FeedbackRow]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, movie_id, title, liked, note, genres_json, year, created_at
                FROM feedback
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()

        output: list[FeedbackRow] = []
        for row in rows:
            output.append(
                FeedbackRow(
                    id=row["id"],
                    user_id=row["user_id"],
                    movie_id=row["movie_id"],
                    title=row["title"],
                    liked=bool(row["liked"]),
                    note=row["note"],
                    genres=json.loads(row["genres_json"] or "[]"),
                    year=row["year"],
                    created_at=row["created_at"],
                )
            )
        return output

    def upsert_seen(self, payload: SeenMovieInput) -> None:
        title_key = self._title_year_key(payload.title, payload.year)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO seen_inventory
                (user_id, movie_id, title, title_key, year, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, movie_id) DO UPDATE SET
                    title = excluded.title,
                    title_key = excluded.title_key,
                    year = excluded.year,
                    source = excluded.source,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    payload.user_id,
                    payload.movie_id,
                    payload.title,
                    title_key,
                    payload.year,
                    payload.source,
                ),
            )

    def remove_seen(self, user_id: str, movie_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM seen_inventory
                WHERE user_id = ? AND movie_id = ?
                """,
                (user_id, movie_id),
            )
        return cursor.rowcount > 0

    def list_seen(
        self,
        user_id: str,
        limit: int = 500,
        query: str | None = None,
    ) -> list[SeenMovieRow]:
        sql = """
            SELECT id, user_id, movie_id, title, year, source, created_at, updated_at
            FROM seen_inventory
            WHERE user_id = ?
        """
        params: list[str | int] = [user_id]
        if query:
            sql += " AND lower(title) LIKE ?"
            params.append(f"%{query.strip().lower()}%")

        sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            SeenMovieRow(
                id=row["id"],
                user_id=row["user_id"],
                movie_id=row["movie_id"],
                title=row["title"],
                year=row["year"],
                source=row["source"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def seen_title_keys(self, user_id: str) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT title_key
                FROM seen_inventory
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchall()
        return {row["title_key"] for row in rows}

    async def preference_similarity(
        self,
        user_id: str,
        title: str,
        overview: str | None,
        genres: list[str],
        top_k: int = 5,
    ) -> tuple[float, list[SimilarFeedback]]:
        target_text = self._compose_embedding_text(title, overview, genres)
        target_embedding = await self._embedding_service.embed(target_text)

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT title, liked, embedding_json
                FROM feedback
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 250
                """,
                (user_id,),
            ).fetchall()

        scored: list[SimilarFeedback] = []
        for row in rows:
            emb = json.loads(row["embedding_json"])
            sim = self._embedding_service.cosine_similarity(target_embedding, emb)
            scored.append(
                SimilarFeedback(
                    title=row["title"],
                    liked=bool(row["liked"]),
                    similarity=sim,
                )
            )

        scored.sort(key=lambda x: x.similarity, reverse=True)
        top = scored[:top_k]

        if not top:
            return 0.0, []

        weighted = [entry.similarity if entry.liked else -entry.similarity for entry in top]
        avg = sum(weighted) / len(weighted)
        normalized = max(min((avg + 1.0) / 2.0, 1.0), 0.0)
        return normalized, top

    async def liked_rag_similarity(
        self,
        user_id: str,
        title: str,
        overview: str | None,
        genres: list[str],
        top_k: int = 5,
    ) -> tuple[float, list[SimilarFeedback]]:
        target_text = self._compose_embedding_text(title, overview, genres)
        target_embedding = await self._embedding_service.embed(target_text)

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT title, embedding_json
                FROM feedback
                WHERE user_id = ? AND liked = 1
                ORDER BY created_at DESC
                LIMIT 250
                """,
                (user_id,),
            ).fetchall()

        scored: list[SimilarFeedback] = []
        for row in rows:
            emb = json.loads(row["embedding_json"])
            sim = self._embedding_service.cosine_similarity(target_embedding, emb)
            scored.append(
                SimilarFeedback(
                    title=row["title"],
                    liked=True,
                    similarity=sim,
                )
            )

        scored.sort(key=lambda x: x.similarity, reverse=True)
        top = scored[:top_k]
        if not top:
            return 0.0, []

        positive = [max(0.0, item.similarity) for item in top]
        avg = sum(positive) / len(positive)
        normalized = max(min(avg, 1.0), 0.0)
        return normalized, top

    @staticmethod
    def _compose_embedding_text(title: str, overview: str | None, genres: list[str]) -> str:
        parts = [title]
        if overview:
            parts.append(overview)
        if genres:
            parts.append(" ".join(genres))
        return "\n".join(parts)

    @staticmethod
    def _title_year_key(title: str, year: int | None) -> str:
        normalized = title.strip().lower()
        return f"{normalized}::{year if year is not None else 'na'}"
