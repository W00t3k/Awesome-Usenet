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
            # Users table for authentication
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT,
                    password_hash TEXT NOT NULL,
                    google_id TEXT,
                    is_active INTEGER DEFAULT 1,
                    is_admin INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_users_username
                ON users(username)
                """
            )
            # Per-user encrypted credentials
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_credentials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    credential_key TEXT NOT NULL,
                    encrypted_value TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE(user_id, credential_key)
                )
                """
            )

            # Sync jobs tracking
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_type TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    started_at TEXT,
                    completed_at TEXT,
                    items_processed INTEGER DEFAULT 0,
                    error_message TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sync_jobs_type_status
                ON sync_jobs(job_type, status)
                """
            )
            # Catalog cache (replaces static JSON)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS catalog_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    catalog_type TEXT UNIQUE NOT NULL,
                    data_json TEXT NOT NULL,
                    synced_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # Run migrations for existing databases
            self._run_migrations(conn)

    def _run_migrations(self, conn: sqlite3.Connection) -> None:
        """Run database migrations for schema updates."""
        # Migration: Add google_id column to users table
        cursor = conn.execute("PRAGMA table_info(users)")
        columns = {row[1] for row in cursor.fetchall()}
        if "google_id" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN google_id TEXT")

        # Create indexes that may not exist
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")

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

    # ===== User methods =====
    def create_user(
        self,
        username: str,
        password_hash: str,
        email: str | None = None,
        google_id: str | None = None,
        is_admin: bool = False,
    ) -> int | None:
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO users (username, email, password_hash, google_id, is_admin)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (username, email, password_hash, google_id, int(is_admin)),
                )
                return cursor.lastrowid
        except Exception:
            return None

    def get_user_by_username(self, username: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, username, email, password_hash, google_id, is_active, is_admin, created_at
                FROM users WHERE username = ?
                """,
                (username,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "password_hash": row["password_hash"],
            "google_id": row["google_id"],
            "is_active": bool(row["is_active"]),
            "is_admin": bool(row["is_admin"]),
            "created_at": row["created_at"],
        }

    def get_user_by_id(self, user_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, username, email, password_hash, google_id, is_active, is_admin, created_at
                FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "password_hash": row["password_hash"],
            "google_id": row["google_id"],
            "is_active": bool(row["is_active"]),
            "is_admin": bool(row["is_admin"]),
            "created_at": row["created_at"],
        }

    def get_user_by_google_id(self, google_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, username, email, password_hash, google_id, is_active, is_admin, created_at
                FROM users WHERE google_id = ?
                """,
                (google_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "password_hash": row["password_hash"],
            "google_id": row["google_id"],
            "is_active": bool(row["is_active"]),
            "is_admin": bool(row["is_admin"]),
            "created_at": row["created_at"],
        }

    def get_user_by_email(self, email: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, username, email, password_hash, google_id, is_active, is_admin, created_at
                FROM users WHERE email = ?
                """,
                (email,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "password_hash": row["password_hash"],
            "google_id": row["google_id"],
            "is_active": bool(row["is_active"]),
            "is_admin": bool(row["is_admin"]),
            "created_at": row["created_at"],
        }

    def update_user_google_id(self, user_id: int, google_id: str) -> bool:
        try:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE users SET google_id = ? WHERE id = ?",
                    (google_id, user_id),
                )
            return True
        except Exception:
            return False

    def list_users(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, username, email, is_active, is_admin, created_at
                FROM users ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "username": row["username"],
                "email": row["email"],
                "is_active": bool(row["is_active"]),
                "is_admin": bool(row["is_admin"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def migrate_anonymous_data(self, anonymous_user_id: str, new_user_id: int) -> dict:
        """Migrate feedback and seen data from anonymous UUID to authenticated user."""
        new_user_key = f"user:{new_user_id}"
        with self._connect() as conn:
            feedback_cursor = conn.execute(
                "UPDATE feedback SET user_id = ? WHERE user_id = ?",
                (new_user_key, anonymous_user_id),
            )
            seen_cursor = conn.execute(
                "UPDATE seen_inventory SET user_id = ? WHERE user_id = ?",
                (new_user_key, anonymous_user_id),
            )
        return {
            "feedback_migrated": feedback_cursor.rowcount,
            "seen_migrated": seen_cursor.rowcount,
        }

    # ===== Sync job methods =====
    def create_sync_job(self, job_type: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO sync_jobs (job_type, status, started_at)
                VALUES (?, 'running', CURRENT_TIMESTAMP)
                """,
                (job_type,),
            )
            return cursor.lastrowid or 0

    def complete_sync_job(
        self,
        job_id: int,
        items_processed: int,
        error_message: str | None = None,
    ) -> None:
        status = "failed" if error_message else "completed"
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sync_jobs
                SET status = ?, completed_at = CURRENT_TIMESTAMP,
                    items_processed = ?, error_message = ?
                WHERE id = ?
                """,
                (status, items_processed, error_message, job_id),
            )

    def recent_sync_jobs(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, job_type, status, started_at, completed_at,
                       items_processed, error_message
                FROM sync_jobs
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "job_type": row["job_type"],
                "status": row["status"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "items_processed": row["items_processed"],
                "error_message": row["error_message"],
            }
            for row in rows
        ]

    def last_sync_job(self, job_type: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, job_type, status, started_at, completed_at,
                       items_processed, error_message
                FROM sync_jobs
                WHERE job_type = ? AND status = 'completed'
                ORDER BY id DESC LIMIT 1
                """,
                (job_type,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "job_type": row["job_type"],
            "status": row["status"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "items_processed": row["items_processed"],
            "error_message": row["error_message"],
        }

    # ===== Catalog cache methods =====
    def get_catalog_cache(self, catalog_type: str) -> tuple[list | None, str | None]:
        """Returns (data, synced_at) or (None, None) if not cached."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT data_json, synced_at FROM catalog_cache
                WHERE catalog_type = ?
                """,
                (catalog_type,),
            ).fetchone()
        if not row:
            return None, None
        return json.loads(row["data_json"]), row["synced_at"]

    def set_catalog_cache(self, catalog_type: str, data: list) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO catalog_cache (catalog_type, data_json, synced_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(catalog_type) DO UPDATE SET
                    data_json = excluded.data_json,
                    synced_at = CURRENT_TIMESTAMP
                """,
                (catalog_type, json.dumps(data)),
            )

    # ===== User credentials methods (encrypted API keys) =====
    def set_user_credential(
        self,
        user_id: int,
        credential_key: str,
        encrypted_value: str,
    ) -> bool:
        """Store an encrypted credential for a user."""
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO user_credentials (user_id, credential_key, encrypted_value)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, credential_key) DO UPDATE SET
                        encrypted_value = excluded.encrypted_value,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, credential_key, encrypted_value),
                )
            return True
        except Exception:
            return False

    def get_user_credential(self, user_id: int, credential_key: str) -> str | None:
        """Get an encrypted credential for a user."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT encrypted_value FROM user_credentials
                WHERE user_id = ? AND credential_key = ?
                """,
                (user_id, credential_key),
            ).fetchone()
        return row["encrypted_value"] if row else None

    def get_user_credentials(self, user_id: int) -> dict[str, str]:
        """Get all encrypted credentials for a user."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT credential_key, encrypted_value FROM user_credentials
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchall()
        return {row["credential_key"]: row["encrypted_value"] for row in rows}

    def delete_user_credential(self, user_id: int, credential_key: str) -> bool:
        """Delete a credential for a user."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM user_credentials
                WHERE user_id = ? AND credential_key = ?
                """,
                (user_id, credential_key),
            )
        return cursor.rowcount > 0
