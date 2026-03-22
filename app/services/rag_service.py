"""
RAG Service - Fast movie knowledge retrieval using Qdrant Cloud.

Indexes movie data (reviews, awards, metadata) for quick retrieval,
reducing LLM token usage and improving response speed.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Collection name for movie knowledge
COLLECTION_NAME = "movie_knowledge"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # Fast, 384 dimensions


class RAGService:
    """RAG service for movie knowledge retrieval."""

    def __init__(
        self,
        qdrant_url: str | None = None,
        qdrant_api_key: str | None = None,
        data_dir: Path | None = None,
    ):
        self._qdrant_url = qdrant_url or os.getenv("QDRANT_URL")
        self._qdrant_api_key = qdrant_api_key or os.getenv("QDRANT_API_KEY")
        self._data_dir = data_dir or Path("data")
        self._client: QdrantClient | None = None
        self._embedder: SentenceTransformer | None = None
        self._initialized = False

    @property
    def available(self) -> bool:
        return bool(self._qdrant_url and self._qdrant_api_key)

    async def initialize(self) -> bool:
        """Initialize Qdrant client and embedder."""
        if self._initialized:
            return True

        if not self.available:
            logger.warning("Qdrant credentials not configured")
            return False

        try:
            # Initialize Qdrant client
            self._client = QdrantClient(
                url=self._qdrant_url,
                api_key=self._qdrant_api_key,
            )

            # Initialize embedder (runs locally, fast)
            self._embedder = SentenceTransformer(EMBEDDING_MODEL)

            # Ensure collection exists
            await self._ensure_collection()

            self._initialized = True
            logger.info("RAG service initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize RAG: {e}")
            return False

    async def _ensure_collection(self) -> None:
        """Create collection if it doesn't exist."""
        collections = self._client.get_collections().collections
        exists = any(c.name == COLLECTION_NAME for c in collections)

        if not exists:
            self._client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(
                    size=384,  # MiniLM-L6-v2 dimension
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info(f"Created collection: {COLLECTION_NAME}")

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for texts."""
        if not self._embedder:
            raise RuntimeError("Embedder not initialized")
        embeddings = self._embedder.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()

    async def index_movie_data(self) -> dict[str, int]:
        """Index all movie data from JSON files."""
        if not self._initialized:
            await self.initialize()

        if not self._client:
            return {"error": "Client not initialized"}

        stats = {"indexed": 0, "files": 0, "errors": 0}
        points = []
        point_id = 0

        # Index all JSON data files
        json_files = list(self._data_dir.glob("*.json"))
        for json_file in json_files:
            try:
                with open(json_file) as f:
                    data = json.load(f)

                source = json_file.stem
                movies = data if isinstance(data, list) else data.get("movies", [])

                for movie in movies:
                    if isinstance(movie, str):
                        # Simple title list
                        text = f"{movie} - {source}"
                        metadata = {"title": movie, "source": source}
                    else:
                        # Full movie object
                        title = movie.get("title", movie.get("name", ""))
                        year = movie.get("year", "")
                        genres = movie.get("genres", [])
                        overview = movie.get("overview", movie.get("description", ""))
                        score = movie.get("tomatometer", movie.get("score", ""))

                        # Build rich text for embedding
                        text_parts = [title]
                        if year:
                            text_parts.append(f"({year})")
                        if genres:
                            text_parts.append(f"Genres: {', '.join(genres)}")
                        if overview:
                            text_parts.append(overview[:500])
                        if score:
                            text_parts.append(f"Score: {score}")
                        text_parts.append(f"Source: {source}")

                        text = " ".join(text_parts)
                        metadata = {
                            "title": title,
                            "year": year,
                            "source": source,
                            "score": score,
                            "genres": ",".join(genres) if genres else "",
                        }

                    if text and len(text) > 10:
                        embedding = self._embed([text])[0]
                        points.append(models.PointStruct(
                            id=point_id,
                            vector=embedding,
                            payload={"text": text[:1000], **metadata},
                        ))
                        point_id += 1
                        stats["indexed"] += 1

                stats["files"] += 1

            except Exception as e:
                logger.error(f"Error indexing {json_file}: {e}")
                stats["errors"] += 1

        # Upsert all points
        if points:
            self._client.upsert(
                collection_name=COLLECTION_NAME,
                points=points,
            )
            logger.info(f"Indexed {len(points)} movie knowledge points")

        return stats

    async def search(
        self,
        query: str,
        limit: int = 5,
        source_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search for relevant movie knowledge."""
        if not self._initialized:
            await self.initialize()

        if not self._client:
            return []

        try:
            # Generate query embedding
            query_embedding = self._embed([query])[0]

            # Build filter if specified
            query_filter = None
            if source_filter:
                query_filter = models.Filter(
                    must=[
                        models.FieldCondition(
                            key="source",
                            match=models.MatchValue(value=source_filter),
                        )
                    ]
                )

            # Search
            results = self._client.search(
                collection_name=COLLECTION_NAME,
                query_vector=query_embedding,
                limit=limit,
                query_filter=query_filter,
            )

            return [
                {
                    "text": hit.payload.get("text", ""),
                    "title": hit.payload.get("title", ""),
                    "source": hit.payload.get("source", ""),
                    "score": hit.score,
                }
                for hit in results
            ]

        except Exception as e:
            logger.error(f"RAG search error: {e}")
            return []

    async def get_movie_context(self, title: str, limit: int = 3) -> str:
        """Get rich context for a specific movie."""
        results = await self.search(title, limit=limit)
        if not results:
            return ""

        context_parts = []
        for r in results:
            context_parts.append(f"[{r['source']}] {r['text'][:300]}")

        return "\n\n".join(context_parts)

    async def enhance_prompt(self, query: str, limit: int = 3) -> str:
        """Enhance a prompt with relevant RAG context."""
        results = await self.search(query, limit=limit)
        if not results:
            return ""

        context = "\n".join([
            f"- {r['title']}: {r['text'][:200]}"
            for r in results
        ])

        return f"Relevant context:\n{context}\n\n"
