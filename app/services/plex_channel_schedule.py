from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from threading import Lock

_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_DEFAULT_TIMES = ["20:00"]


@dataclass
class PlexChannelScheduleState:
    enabled: bool = False
    playlist_name: str = "Majic TV Station"
    count: int = 25
    min_year: int | None = None
    max_year: int | None = None
    schedule_times: list[str] = field(default_factory=lambda: list(_DEFAULT_TIMES))
    interval_minutes: int = 0
    autoplay_enabled: bool = True
    autoplay_client: str | None = None
    autoplay_random_offset: bool = True
    last_run_at: str | None = None
    last_run_source: str | None = None
    last_run_status: str | None = None
    last_run_message: str | None = None
    last_queue_size: int = 0
    last_run_slots: dict[str, str] = field(default_factory=dict)
    last_play_attempt_at: str | None = None
    last_play_started_at: str | None = None
    last_play_status: str | None = None
    last_play_message: str | None = None
    last_play_movie: str | None = None
    last_play_client: str | None = None
    last_play_offset_ms: int = 0


class PlexChannelScheduleService:
    """Persistent schedule/config state for Plex TV channel playlist rotation."""

    def __init__(self, state_path: Path):
        self._state_path = state_path
        self._lock = Lock()
        self._state = self._load()

    def snapshot(self, now: datetime | None = None) -> dict:
        with self._lock:
            payload = asdict(self._state)
            payload["schedule_times"] = list(self._state.schedule_times)
            payload["next_run_at"] = self._next_run_at_locked(now=now)
            return payload

    def update_config(
        self,
        *,
        enabled: bool,
        playlist_name: str,
        count: int,
        min_year: int | None,
        max_year: int | None,
        schedule_times: list[str],
        interval_minutes: int,
        autoplay_enabled: bool,
        autoplay_client: str | None,
        autoplay_random_offset: bool,
    ) -> dict:
        name = (playlist_name or "").strip() or "Majic TV Station"
        queue_size = max(1, min(int(count), 250))
        times = self._normalize_times(schedule_times)
        interval = max(0, min(int(interval_minutes), 1440))
        client = str(autoplay_client or "").strip() or None

        min_y = int(min_year) if min_year is not None else None
        max_y = int(max_year) if max_year is not None else None
        if min_y is not None and max_y is not None and min_y > max_y:
            min_y, max_y = max_y, min_y

        with self._lock:
            self._state.enabled = bool(enabled)
            self._state.playlist_name = name
            self._state.count = queue_size
            self._state.min_year = min_y
            self._state.max_year = max_y
            self._state.schedule_times = times
            self._state.interval_minutes = interval
            self._state.autoplay_enabled = bool(autoplay_enabled)
            self._state.autoplay_client = client
            self._state.autoplay_random_offset = bool(autoplay_random_offset)
            # Keep only slot history for currently configured times.
            self._state.last_run_slots = {
                slot: day
                for slot, day in self._state.last_run_slots.items()
                if slot in set(times)
            }
            self._save_locked()
            payload = asdict(self._state)
            payload["next_run_at"] = self._next_run_at_locked()
            return payload

    def due_slot(self, now: datetime | None = None) -> str | None:
        current = now or datetime.now().astimezone()
        slot = current.strftime("%H:%M")

        with self._lock:
            if not self._state.enabled:
                return None
            if slot not in self._state.schedule_times:
                return None
            if self._state.last_run_slots.get(slot) == current.date().isoformat():
                return None
            return slot

    def due_interval(self, now: datetime | None = None) -> bool:
        current = now or datetime.now().astimezone()
        with self._lock:
            if not self._state.enabled:
                return False
            interval = int(self._state.interval_minutes or 0)
            if interval <= 0:
                return False
            last = self._state.last_run_at
            if not last:
                return True
            try:
                last_dt = datetime.fromisoformat(str(last))
            except ValueError:
                return True
            return last_dt + timedelta(minutes=interval) <= current

    def mark_run(
        self,
        *,
        success: bool,
        message: str,
        queue_size: int,
        source: str,
        slot: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        current = now or datetime.now().astimezone()
        status = "ok" if success else "error"

        with self._lock:
            self._state.last_run_at = current.isoformat()
            self._state.last_run_source = source
            self._state.last_run_status = status
            self._state.last_run_message = (message or "").strip()[:600]
            self._state.last_queue_size = max(0, int(queue_size))
            if slot:
                self._state.last_run_slots[slot] = current.date().isoformat()
            self._save_locked()
            payload = asdict(self._state)
            payload["next_run_at"] = self._next_run_at_locked(now=current)
            return payload

    def mark_playback(
        self,
        *,
        success: bool,
        message: str,
        movie_title: str | None,
        client_name: str | None,
        offset_ms: int = 0,
        now: datetime | None = None,
    ) -> dict:
        current = now or datetime.now().astimezone()
        status = "ok" if success else "error"

        with self._lock:
            self._state.last_play_attempt_at = current.isoformat()
            self._state.last_play_status = status
            self._state.last_play_message = (message or "").strip()[:600]
            self._state.last_play_movie = (str(movie_title or "").strip() or None)
            self._state.last_play_client = (str(client_name or "").strip() or None)
            self._state.last_play_offset_ms = max(0, int(offset_ms))
            if success:
                self._state.last_play_started_at = current.isoformat()
            self._save_locked()
            payload = asdict(self._state)
            payload["next_run_at"] = self._next_run_at_locked(now=current)
            return payload

    def _load(self) -> PlexChannelScheduleState:
        try:
            raw = self._state_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return self._coerce_state(data)
        except Exception:
            return PlexChannelScheduleState()

    def _save_locked(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self._state)
        self._state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _next_run_at_locked(self, now: datetime | None = None) -> str | None:
        current = now or datetime.now().astimezone()
        if not self._state.enabled:
            return None

        interval_candidate: datetime | None = None
        interval = int(self._state.interval_minutes or 0)
        if interval > 0:
            last = self._state.last_run_at
            if last:
                try:
                    last_dt = datetime.fromisoformat(str(last))
                    interval_candidate = last_dt + timedelta(minutes=interval)
                except ValueError:
                    interval_candidate = current
            else:
                interval_candidate = current

        schedule_candidate: datetime | None = None
        for day_offset in (0, 1, 2):
            day_base = current + timedelta(days=day_offset)
            for slot in self._state.schedule_times:
                hour, minute = [int(part) for part in slot.split(":", 1)]
                candidate = day_base.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if candidate < current:
                    continue
                if day_offset == 0 and self._state.last_run_slots.get(slot) == current.date().isoformat() and candidate <= current:
                    continue
                schedule_candidate = candidate
                break
            if schedule_candidate is not None:
                break

        if interval_candidate is None and schedule_candidate is None:
            return None
        if interval_candidate is None:
            return schedule_candidate.isoformat()
        if schedule_candidate is None:
            return interval_candidate.isoformat()
        return (interval_candidate if interval_candidate <= schedule_candidate else schedule_candidate).isoformat()

    @staticmethod
    def _normalize_times(raw_times: list[str] | None) -> list[str]:
        times = raw_times or []
        normalized: set[str] = set()
        for raw in times:
            text = str(raw or "").strip()
            if not text:
                continue
            if not _TIME_RE.match(text):
                raise ValueError(f"Invalid schedule time '{text}'. Use HH:MM (24-hour).")
            hour, minute = text.split(":", 1)
            hh = int(hour)
            mm = int(minute)
            if hh < 0 or hh > 23 or mm < 0 or mm > 59:
                raise ValueError(f"Invalid schedule time '{text}'. Use HH:MM (24-hour).")
            normalized.add(f"{hh:02d}:{mm:02d}")
        if not normalized:
            return list(_DEFAULT_TIMES)
        return sorted(normalized)

    @classmethod
    def _coerce_state(cls, raw: dict) -> PlexChannelScheduleState:
        enabled = bool(raw.get("enabled", False))
        playlist_name = str(raw.get("playlist_name") or "Majic TV Station").strip() or "Majic TV Station"

        try:
            count = int(raw.get("count", 25))
        except Exception:
            count = 25
        count = max(1, min(count, 250))

        min_year = raw.get("min_year")
        max_year = raw.get("max_year")
        try:
            min_year = int(min_year) if min_year is not None else None
        except Exception:
            min_year = None
        try:
            max_year = int(max_year) if max_year is not None else None
        except Exception:
            max_year = None
        if min_year is not None and max_year is not None and min_year > max_year:
            min_year, max_year = max_year, min_year

        schedule_times = cls._normalize_times(list(raw.get("schedule_times") or []))
        try:
            interval_minutes = int(raw.get("interval_minutes") or 0)
        except Exception:
            interval_minutes = 0
        interval_minutes = max(0, min(interval_minutes, 1440))
        autoplay_enabled = bool(raw.get("autoplay_enabled", True))
        autoplay_client = str(raw.get("autoplay_client") or "").strip() or None
        autoplay_random_offset = bool(raw.get("autoplay_random_offset", True))

        last_run_slots_raw = raw.get("last_run_slots") or {}
        last_run_slots = {
            str(slot): str(day)
            for slot, day in last_run_slots_raw.items()
            if str(slot) in set(schedule_times)
        }

        return PlexChannelScheduleState(
            enabled=enabled,
            playlist_name=playlist_name,
            count=count,
            min_year=min_year,
            max_year=max_year,
            schedule_times=schedule_times,
            interval_minutes=interval_minutes,
            autoplay_enabled=autoplay_enabled,
            autoplay_client=autoplay_client,
            autoplay_random_offset=autoplay_random_offset,
            last_run_at=(str(raw.get("last_run_at")) if raw.get("last_run_at") else None),
            last_run_source=(str(raw.get("last_run_source")) if raw.get("last_run_source") else None),
            last_run_status=(str(raw.get("last_run_status")) if raw.get("last_run_status") else None),
            last_run_message=(str(raw.get("last_run_message")) if raw.get("last_run_message") else None),
            last_queue_size=max(0, int(raw.get("last_queue_size") or 0)),
            last_run_slots=last_run_slots,
            last_play_attempt_at=(str(raw.get("last_play_attempt_at")) if raw.get("last_play_attempt_at") else None),
            last_play_started_at=(str(raw.get("last_play_started_at")) if raw.get("last_play_started_at") else None),
            last_play_status=(str(raw.get("last_play_status")) if raw.get("last_play_status") else None),
            last_play_message=(str(raw.get("last_play_message")) if raw.get("last_play_message") else None),
            last_play_movie=(str(raw.get("last_play_movie")) if raw.get("last_play_movie") else None),
            last_play_client=(str(raw.get("last_play_client")) if raw.get("last_play_client") else None),
            last_play_offset_ms=max(0, int(raw.get("last_play_offset_ms") or 0)),
        )
