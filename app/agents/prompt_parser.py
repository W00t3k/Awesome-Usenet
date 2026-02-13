from __future__ import annotations

import re
from datetime import datetime

from app.services.models import Preferences

GENRE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bsci[- ]?fi\b|\bscience fiction\b", "sci-fi"),
    (r"\baction\b", "action"),
    (r"\bcomedy\b|\bfunny\b", "comedy"),
    (r"\bdrama\b", "drama"),
    (r"\bromance\b|\bromantic\b", "romance"),
    (r"\bmystery\b|\bwhodunit\b", "mystery"),
    (r"\banimation\b|\banime\b", "animation"),
    (r"\bfantasy\b", "fantasy"),
    (r"\bthriller\b", "thriller"),
    (r"\badventure\b", "adventure"),
    (r"\bmusical\b|\bmusic\b", "musical"),
)

MOOD_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bfun\b|\bfunny\b|\blight\b", "funny"),
    (r"\buplifting\b|\bfeel[- ]?good\b|\bheartwarming\b", "uplifting"),
    (r"\bcozy\b|\bcomfort\b", "cozy"),
    (r"\btense\b|\bintense\b", "tense"),
    (r"\bmind[- ]?bending\b|\btrippy\b", "mind_bending"),
    (r"\bromantic\b|\blove\b", "romantic"),
    (r"\badventurous\b|\bepic\b", "adventurous"),
    (r"\bdark\b|\bgritty\b", "dark"),
    (r"\binspiring\b|\bmotivating\b", "inspiring"),
    (r"\bemotional\b|\btearjerker\b", "emotional"),
    (r"\bthoughtful\b|\breflective\b", "thoughtful"),
)


def _parse_max_runtime(text: str) -> int | None:
    minutes_match = re.search(
        r"\b(?:under|max|less than|up to)\s+(\d{2,3})\s*(?:minutes|mins|min)\b",
        text,
    )
    if minutes_match:
        return int(minutes_match.group(1))

    hours_match = re.search(
        r"\b(?:under|max|less than|up to)\s+(\d(?:\.\d)?)\s*hours?\b",
        text,
    )
    if hours_match:
        return int(float(hours_match.group(1)) * 60)

    return None


def _parse_min_year(text: str) -> int | None:
    after_match = re.search(r"\b(?:after|since)\s+(19\d{2}|20\d{2})\b", text)
    if after_match:
        return int(after_match.group(1))

    if re.search(r"\brecent\b|\bnew\b|\bnewer\b|\bmodern\b", text):
        return datetime.now().year - 10

    return None


def parse_prompt(prompt: str) -> Preferences:
    text = prompt.lower()
    preferences = Preferences()

    for pattern, genre in GENRE_PATTERNS:
        if re.search(pattern, text):
            preferences.genres.add(genre)

    for pattern, mood in MOOD_PATTERNS:
        if re.search(pattern, text):
            preferences.moods.add(mood)

    preferences.max_runtime_minutes = _parse_max_runtime(text)
    preferences.min_year = _parse_min_year(text)
    preferences.family_only = bool(
        re.search(r"\bfamily\b|\bkids?\b|\bchildren\b|\bkid[- ]?friendly\b", text)
    )

    return preferences
