from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import random
import secrets


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class StationState:
    station_id: str
    name: str
    seed: int
    queue: list[dict]
    current_index: int
    created_at: str
    updated_at: str
    started_at: str
    cycle: int


class PlexStationService:
    """In-memory random movie channel backed by Plex library rows."""

    def __init__(self, max_stations: int = 20, max_queue_size: int = 250):
        self._max_stations = max_stations
        self._max_queue_size = max_queue_size
        self._stations: dict[str, StationState] = {}

    def create_station(
        self,
        library_rows: list[dict],
        *,
        name: str,
        count: int,
        seed: int | None = None,
        min_year: int | None = None,
        max_year: int | None = None,
    ) -> dict:
        rng_seed = int(seed) if seed is not None else random.SystemRandom().randint(1, 2_000_000_000)
        queue = self.build_queue(
            library_rows,
            count=count,
            seed=rng_seed,
            min_year=min_year,
            max_year=max_year,
        )

        if len(self._stations) >= self._max_stations:
            oldest = sorted(self._stations.values(), key=lambda item: item.updated_at)[0]
            self._stations.pop(oldest.station_id, None)

        now = _now_iso()
        station_id = secrets.token_urlsafe(6)
        state = StationState(
            station_id=station_id,
            name=name.strip() or "Random Plex TV",
            seed=rng_seed,
            queue=queue,
            current_index=0,
            created_at=now,
            updated_at=now,
            started_at=now,
            cycle=0,
        )
        self._stations[station_id] = state
        return self._serialize(state)

    def build_queue(
        self,
        library_rows: list[dict],
        *,
        count: int,
        seed: int | None = None,
        min_year: int | None = None,
        max_year: int | None = None,
    ) -> list[dict]:
        queue_size = max(1, min(count, self._max_queue_size))
        rng_seed = int(seed) if seed is not None else random.SystemRandom().randint(1, 2_000_000_000)
        candidates = self._build_candidates(
            library_rows,
            min_year=min_year,
            max_year=max_year,
        )
        if not candidates:
            raise ValueError("No eligible Plex movies found for station")

        rng = random.Random(rng_seed)
        rng.shuffle(candidates)
        return candidates[: min(queue_size, len(candidates))]

    def list_stations(self) -> list[dict]:
        states = sorted(self._stations.values(), key=lambda item: item.updated_at, reverse=True)
        return [self._serialize(state, compact=True) for state in states]

    def get_station(self, station_id: str) -> dict | None:
        state = self._stations.get(station_id)
        return self._serialize(state) if state else None

    def delete_station(self, station_id: str) -> bool:
        return self._stations.pop(station_id, None) is not None

    def next_movie(self, station_id: str) -> dict:
        state = self._require_station(station_id)
        if not state.queue:
            raise ValueError("Station queue is empty")

        state.current_index += 1
        if state.current_index >= len(state.queue):
            state.current_index = 0
            state.cycle += 1
        state.updated_at = _now_iso()
        state.started_at = state.updated_at
        return self._serialize(state)

    def _require_station(self, station_id: str) -> StationState:
        state = self._stations.get(station_id)
        if not state:
            raise KeyError("Station not found")
        return state

    @staticmethod
    def _build_candidates(
        library_rows: list[dict],
        *,
        min_year: int | None,
        max_year: int | None,
    ) -> list[dict]:
        out: list[dict] = []
        for row in library_rows:
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            rating_key = str(row.get("ratingKey") or "").strip()
            if not rating_key:
                continue
            year = row.get("year")
            if isinstance(year, int):
                if min_year is not None and year < min_year:
                    continue
                if max_year is not None and year > max_year:
                    continue
            elif min_year is not None or max_year is not None:
                continue

            out.append(
                {
                    "title": title,
                    "year": year if isinstance(year, int) else None,
                    "rating_key": rating_key,
                    "duration_ms": row.get("duration"),
                    "summary": row.get("summary"),
                    "thumb": row.get("thumb"),
                    "added_at": row.get("addedAt"),
                }
            )
        return out

    def _serialize(self, state: StationState | None, compact: bool = False) -> dict | None:
        if not state:
            return None
        queue_len = len(state.queue)
        now_playing = state.queue[state.current_index] if queue_len else None
        if compact:
            return {
                "station_id": state.station_id,
                "name": state.name,
                "queue_size": queue_len,
                "current_index": state.current_index,
                "created_at": state.created_at,
                "updated_at": state.updated_at,
                "cycle": state.cycle,
                "now_playing": now_playing,
            }

        up_next = []
        if queue_len:
            for step in range(1, min(queue_len, 8)):
                idx = (state.current_index + step) % queue_len
                up_next.append(state.queue[idx])

        return {
            "station_id": state.station_id,
            "name": state.name,
            "seed": state.seed,
            "queue_size": queue_len,
            "current_index": state.current_index,
            "created_at": state.created_at,
            "updated_at": state.updated_at,
            "started_at": state.started_at,
            "cycle": state.cycle,
            "now_playing": now_playing,
            "up_next": up_next,
            "queue": state.queue,
        }
