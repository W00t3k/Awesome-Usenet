from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Movie:
    title: str
    year: int
    runtime_minutes: int
    genres: tuple[str, ...]
    mood_tags: tuple[str, ...]
    family_friendly: bool = False
    synopsis: str = ""


@dataclass
class Preferences:
    moods: set[str] = field(default_factory=set)
    genres: set[str] = field(default_factory=set)
    max_runtime_minutes: int | None = None
    min_year: int | None = None
    family_only: bool = False
