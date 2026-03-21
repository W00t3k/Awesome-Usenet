from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from app.agents.base import MovieAgent
from app.clients.oscars_web_client import OscarsWebClient
from app.models import AgentContext, MovieCandidate, SourcePayload

if TYPE_CHECKING:
    from app.services.memory_store import MemoryStore


class OscarAgent(MovieAgent):
    goal = "Find high-confidence Oscar winners and nominees with enough metadata to rank and act on."
    name = "oscars"

    def __init__(
        self,
        dataset_path: Path,
        memory_store: "MemoryStore | None" = None,
        timeout_seconds: float = 8.0,
        web_client: OscarsWebClient | None = None,
    ):
        self._dataset_path = dataset_path
        self._memory_store = memory_store
        self._web_client = web_client or OscarsWebClient(timeout_seconds=timeout_seconds)

    async def collect(self, context: AgentContext) -> SourcePayload:
        rows = self._load_data()
        source_name = "local/cache dataset"

        if not rows:
            rows = await self._load_data_from_web()
            source_name = "web fallback"

        if not rows:
            return SourcePayload(
                metadata={
                    "notes": (
                        "Oscars dataset missing and web fallback failed; "
                        "could not extract Best Picture winners"
                    )
                }
            )

        movies: list[MovieCandidate] = []
        seen_keys: set[str] = set()

        for row in sorted(rows, key=lambda r: int(r.get("year") or 0), reverse=True):
            year = self._coerce_year(row.get("year"))
            winner = self._normalize_title(row.get("winner"))
            best_actor = self._normalize_person(row.get("best_actor"))
            best_actor_film = self._normalize_title(row.get("best_actor_film"))
            actor_film_key = self._movie_key(best_actor_film, year) if best_actor_film else None

            if winner:
                winner_key = self._movie_key(winner, year)
                seen_keys.add(winner_key)
                award_labels = [f"Best Picture winner ({year})"] if year else ["Best Picture winner"]
                source_tags = ["oscars", "best-picture-winner"]
                winner_best_actor: str | None = None
                if best_actor and actor_film_key == winner_key:
                    award_labels.append(f"Best Actor winner: {best_actor}")
                    source_tags.append("best-actor-winner")
                    winner_best_actor = best_actor
                movies.append(
                    MovieCandidate(
                        movie_id=f"oscars:{winner.lower().replace(' ', '_')}",
                        title=winner,
                        normalized_title=self._normalized_key(winner),
                        year=year,
                        best_picture=True,
                        best_actor=winner_best_actor,
                        award_labels=award_labels,
                        source_tags=source_tags,
                        evidence=award_labels,
                    )
                )

            for nominee_raw in row.get("nominees", []):
                nominee = self._normalize_title(nominee_raw)
                if not nominee:
                    continue
                nominee_key = self._movie_key(nominee, year)
                seen_keys.add(nominee_key)
                source_tags = ["oscars", "best-picture-nominee"]
                award_labels = [f"Best Picture nominee ({year})"] if year else ["Best Picture nominee"]
                nominee_best_actor: str | None = None
                if best_actor and actor_film_key == nominee_key:
                    source_tags.append("best-actor-winner")
                    nominee_best_actor = best_actor
                    award_labels.append(
                        f"Best Actor winner ({year}): {best_actor}"
                        if year
                        else f"Best Actor winner: {best_actor}"
                    )
                movies.append(
                    MovieCandidate(
                        movie_id=f"oscars:{nominee.lower().replace(' ', '_')}",
                        title=nominee,
                        normalized_title=self._normalized_key(nominee),
                        year=year,
                        best_picture=True,
                        best_actor=nominee_best_actor,
                        award_labels=award_labels,
                        source_tags=source_tags,
                        evidence=award_labels,
                    )
                )

            if best_actor and best_actor_film:
                actor_film_key = self._movie_key(best_actor_film, year)
                if actor_film_key not in seen_keys:
                    seen_keys.add(actor_film_key)
                    movies.append(
                        MovieCandidate(
                            movie_id=f"oscars:{best_actor_film.lower().replace(' ', '_')}",
                            title=best_actor_film,
                            normalized_title=self._normalized_key(best_actor_film),
                            year=year,
                            best_actor=best_actor,
                            award_labels=[f"Best Actor winner ({year}): {best_actor}"] if year else [f"Best Actor winner: {best_actor}"],
                            source_tags=["oscars", "best-actor-winner"],
                            evidence=[f"Best Actor winner ({year}): {best_actor}"] if year else [f"Best Actor winner: {best_actor}"],
                        )
                    )

        return SourcePayload(
            movies=movies,
            metadata={"notes": f"Loaded {len(rows)} Oscar years from {source_name}"},
        )

    def _load_data(self) -> list[dict]:
        """Load Oscar data from cache first, then fallback to JSON file."""
        # Try catalog cache first
        if self._memory_store:
            try:
                cached_data, synced_at = self._memory_store.get_catalog_cache("oscars")
                if cached_data:
                    return cached_data
            except Exception:
                pass

        # Fallback to JSON file
        if self._dataset_path.exists():
            try:
                return json.loads(self._dataset_path.read_text())
            except Exception:
                pass

        return []

    async def _load_data_from_web(self) -> list[dict]:
        try:
            best_picture_rows = await self._web_client.fetch_best_picture_rows(limit_years=40)
            best_actor_rows = await self._web_client.fetch_best_actor_rows(limit_years=40)
        except Exception:
            return []

        if not best_picture_rows:
            return []

        actor_by_year = {
            self._coerce_year(row.get("year")): row
            for row in best_actor_rows
            if self._coerce_year(row.get("year")) is not None
        }

        enriched_rows: list[dict] = []
        for row in best_picture_rows:
            year = self._coerce_year(row.get("year"))
            actor_row = actor_by_year.get(year)
            enriched = dict(row)
            if actor_row:
                enriched["best_actor"] = actor_row.get("best_actor")
                enriched["best_actor_film"] = actor_row.get("best_actor_film")
            enriched_rows.append(enriched)
        return enriched_rows

    @staticmethod
    def _normalize_title(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        text = text.replace("’", "'")
        text = " ".join(text.split())
        text = text.removeprefix('"').removesuffix('"').strip()
        return text or None

    @staticmethod
    def _normalize_person(value: object) -> str | None:
        text = OscarAgent._normalize_title(value)
        return text

    @staticmethod
    def _coerce_year(value: object) -> int | None:
        if value is None:
            return None
        try:
            text = str(value)
            year = int(text[:4]) if len(text) >= 4 else int(text)
            if 1900 <= year <= 2100:
                return year
        except Exception:
            return None
        return None

    @staticmethod
    def _normalized_key(title: str) -> str:
        return "".join(ch for ch in title.lower() if ch.isalnum())

    @staticmethod
    def _movie_key(title: str, year: int | None) -> str:
        return f"{OscarAgent._normalized_key(title)}::{year if year is not None else 'na'}"
