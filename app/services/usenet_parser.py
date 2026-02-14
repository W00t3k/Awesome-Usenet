"""Enhanced usenet release parser with quality detection and deduplication."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ParsedRelease:
    """Parsed usenet release with extracted metadata."""

    title: str
    year: int | None = None
    quality: Literal["2160p", "1080p", "720p", "480p", "unknown"] = "unknown"
    source: Literal[
        "BluRay", "WEB-DL", "WEBRip", "HDTV", "DVDRip", "BDRip", "Remux", "unknown"
    ] = "unknown"
    codec: Literal["x265", "x264", "HEVC", "H.264", "AV1", "unknown"] = "unknown"
    audio: Literal[
        "Atmos", "DTS-HD MA", "DTS-HD", "DTS", "TrueHD", "DD+", "DD", "AAC", "unknown"
    ] = "unknown"
    is_proper: bool = False
    is_repack: bool = False
    release_group: str | None = None
    is_extended: bool = False
    is_directors_cut: bool = False
    is_criterion: bool = False
    is_remux: bool = False
    is_hdr: bool = False
    is_tv_release: bool = False
    raw_title: str = ""
    score: int = field(default=0)

    def __post_init__(self) -> None:
        self.score = self._calculate_score()

    def _calculate_score(self) -> int:
        """Calculate quality score for ranking releases."""
        score = 0

        # Quality scoring
        quality_scores = {"2160p": 100, "1080p": 80, "720p": 60, "480p": 40, "unknown": 20}
        score += quality_scores.get(self.quality, 20)

        # Source scoring
        source_scores = {
            "Remux": 50,
            "BluRay": 40,
            "WEB-DL": 35,
            "WEBRip": 30,
            "HDTV": 20,
            "BDRip": 25,
            "DVDRip": 15,
            "unknown": 0,
        }
        score += source_scores.get(self.source, 0)

        # Codec scoring
        codec_scores = {"x265": 20, "HEVC": 20, "AV1": 25, "x264": 15, "H.264": 15, "unknown": 0}
        score += codec_scores.get(self.codec, 0)

        # Audio scoring
        audio_scores = {
            "Atmos": 30,
            "DTS-HD MA": 25,
            "TrueHD": 25,
            "DTS-HD": 20,
            "DTS": 15,
            "DD+": 12,
            "DD": 10,
            "AAC": 8,
            "unknown": 0,
        }
        score += audio_scores.get(self.audio, 0)

        # Bonuses
        if self.is_hdr:
            score += 20
        if self.is_remux:
            score += 30
        if self.is_criterion:
            score += 15
        if self.is_extended or self.is_directors_cut:
            score += 10
        if self.is_proper or self.is_repack:
            score += 5

        return score


# Quality patterns
QUALITY_PATTERNS = [
    (re.compile(r"\b2160p\b", re.I), "2160p"),
    (re.compile(r"\b4K\b", re.I), "2160p"),
    (re.compile(r"\bUHD\b", re.I), "2160p"),
    (re.compile(r"\b1080p\b", re.I), "1080p"),
    (re.compile(r"\b720p\b", re.I), "720p"),
    (re.compile(r"\b480p\b", re.I), "480p"),
    (re.compile(r"\bSD\b", re.I), "480p"),
]

# Source patterns
SOURCE_PATTERNS = [
    (re.compile(r"\bRemux\b", re.I), "Remux"),
    (re.compile(r"\bBlu-?Ray\b", re.I), "BluRay"),
    (re.compile(r"\bBDRip\b", re.I), "BDRip"),
    (re.compile(r"\bWEB-?DL\b", re.I), "WEB-DL"),
    (re.compile(r"\bWEB-?Rip\b", re.I), "WEBRip"),
    (re.compile(r"\bWEB\b", re.I), "WEB-DL"),
    (re.compile(r"\bHDTV\b", re.I), "HDTV"),
    (re.compile(r"\bDVDRip\b", re.I), "DVDRip"),
    (re.compile(r"\bDVD\b", re.I), "DVDRip"),
]

# Codec patterns
CODEC_PATTERNS = [
    (re.compile(r"\bx265\b", re.I), "x265"),
    (re.compile(r"\bHEVC\b", re.I), "HEVC"),
    (re.compile(r"\bH\.?265\b", re.I), "x265"),
    (re.compile(r"\bx264\b", re.I), "x264"),
    (re.compile(r"\bH\.?264\b", re.I), "H.264"),
    (re.compile(r"\bAVC\b", re.I), "H.264"),
    (re.compile(r"\bAV1\b", re.I), "AV1"),
]

# Audio patterns (order matters - check more specific first)
AUDIO_PATTERNS = [
    (re.compile(r"\bAtmos\b", re.I), "Atmos"),
    (re.compile(r"\bTrueHD\b", re.I), "TrueHD"),
    (re.compile(r"\bDTS-?HD[\s.-]?MA\b", re.I), "DTS-HD MA"),
    (re.compile(r"\bDTS-?HD\b", re.I), "DTS-HD"),
    (re.compile(r"\bDTS\b", re.I), "DTS"),
    (re.compile(r"\bDD\+\b", re.I), "DD+"),
    (re.compile(r"\bDDP?\b", re.I), "DD"),
    (re.compile(r"\bAC3\b", re.I), "DD"),
    (re.compile(r"\bAAC\b", re.I), "AAC"),
    (re.compile(r"\bFLAC\b", re.I), "DTS"),  # Treat FLAC as high quality
]

# Special edition patterns
PROPER_PATTERN = re.compile(r"\bPROPER\b", re.I)
REPACK_PATTERN = re.compile(r"\bREPACK\b", re.I)
EXTENDED_PATTERN = re.compile(r"\bEXTENDED\b", re.I)
DIRECTORS_CUT_PATTERN = re.compile(r"\b(DIRECTORS?[._-]?CUT|DC)\b", re.I)
CRITERION_PATTERN = re.compile(r"\bCRITERION\b", re.I)
REMUX_PATTERN = re.compile(r"\bREMUX\b", re.I)
HDR_PATTERN = re.compile(r"\b(HDR|HDR10\+?|DV|Dolby[._-]?Vision)\b", re.I)

# Release group pattern (typically at the end after a dash)
GROUP_PATTERN = re.compile(r"-([A-Za-z0-9]+)(?:\.[a-z]{2,4})?$")

# Year extraction pattern
YEAR_PATTERN = re.compile(r"\b(19\d{2}|20\d{2})\b")

# TV episode markers (exclude from movie recommendations)
TV_PATTERNS = [
    re.compile(r"\bS\d{1,4}E\d{1,3}\b", re.I),
    re.compile(r"\b\d{1,2}x\d{1,3}\b", re.I),
    re.compile(r"\bSeason[ ._-]?\d{1,2}\b", re.I),
    re.compile(r"\bSeason[ ._-]?\d{1,4}[ ._-]?Episode[ ._-]?\d{1,3}\b", re.I),
    re.compile(r"\bComplete[ ._-]+Season\b", re.I),
    re.compile(r"\bEpisode[ ._-]?\d{1,3}\b", re.I),
]

TITLE_STOP_PATTERN = re.compile(
    r"\b("
    r"S\d{1,4}E\d{1,3}|"
    r"\d{1,2}x\d{1,3}|"
    r"19\d{2}|20\d{2}|"
    r"2160p|1080p|720p|480p|4K|UHD|"
    r"Blu-?Ray|WEB-?DL|WEB-?Rip|HDTV|DVDRip|BDRip|Remux|"
    r"x265|x264|HEVC|H\.?264|AV1|"
    r"Atmos|DTS-?HD(?:[\s.-]?MA)?|DTS|TrueHD|DD\+?|AAC|FLAC(?:\s*\d(?:\.\d)?)?|AC3|"
    r"PROPER|REPACK|EXTENDED|DIRECTOR.?S?.?CUT|CRITERION|REMUX|HDR10\+?|HDR|DV|Dolby.?Vision|"
    r"WEB|SD|AVC"
    r")\b",
    re.I,
)


def is_likely_tv_release(raw_title: str) -> bool:
    """Detect TV episode/season releases so they can be excluded from movie lists."""
    normalized = re.sub(r"[._]", " ", raw_title)
    return any(pattern.search(normalized) for pattern in TV_PATTERNS)


def parse_release(raw_title: str) -> ParsedRelease:
    """Parse a usenet release title into structured metadata."""
    # Normalize separators
    normalized = re.sub(r"[._]", " ", raw_title)
    is_tv_release = is_likely_tv_release(raw_title)

    # Extract quality
    quality: Literal["2160p", "1080p", "720p", "480p", "unknown"] = "unknown"
    for pattern, value in QUALITY_PATTERNS:
        if pattern.search(normalized):
            quality = value  # type: ignore
            break

    # Extract source
    source: Literal[
        "BluRay", "WEB-DL", "WEBRip", "HDTV", "DVDRip", "BDRip", "Remux", "unknown"
    ] = "unknown"
    for pattern, value in SOURCE_PATTERNS:
        if pattern.search(normalized):
            source = value  # type: ignore
            break

    # Extract codec
    codec: Literal["x265", "x264", "HEVC", "H.264", "AV1", "unknown"] = "unknown"
    for pattern, value in CODEC_PATTERNS:
        if pattern.search(normalized):
            codec = value  # type: ignore
            break

    # Extract audio
    audio: Literal[
        "Atmos", "DTS-HD MA", "DTS-HD", "DTS", "TrueHD", "DD+", "DD", "AAC", "unknown"
    ] = "unknown"
    for pattern, value in AUDIO_PATTERNS:
        if pattern.search(normalized):
            audio = value  # type: ignore
            break

    # Extract special flags
    is_proper = bool(PROPER_PATTERN.search(normalized))
    is_repack = bool(REPACK_PATTERN.search(normalized))
    is_extended = bool(EXTENDED_PATTERN.search(normalized))
    is_directors_cut = bool(DIRECTORS_CUT_PATTERN.search(normalized))
    is_criterion = bool(CRITERION_PATTERN.search(normalized))
    is_remux = bool(REMUX_PATTERN.search(normalized))
    is_hdr = bool(HDR_PATTERN.search(normalized))

    # Extract release group
    release_group = None
    group_match = GROUP_PATTERN.search(raw_title)
    if group_match:
        release_group = group_match.group(1)

    # Extract year
    year_match = YEAR_PATTERN.search(normalized)
    year = int(year_match.group(1)) if year_match else None

    # Extract clean title (everything before the year or quality markers)
    title = _extract_title(normalized, year)

    return ParsedRelease(
        title=title,
        year=year,
        quality=quality,
        source=source,
        codec=codec,
        audio=audio,
        is_proper=is_proper,
        is_repack=is_repack,
        release_group=release_group,
        is_extended=is_extended,
        is_directors_cut=is_directors_cut,
        is_criterion=is_criterion,
        is_remux=is_remux,
        is_hdr=is_hdr,
        is_tv_release=is_tv_release,
        raw_title=raw_title,
    )


def _extract_title(normalized: str, year: int | None) -> str:
    """Extract clean movie title from normalized release name."""
    cutoff = len(normalized)

    if year:
        year_match = re.search(rf"\b{year}\b", normalized)
        if year_match:
            cutoff = min(cutoff, year_match.start())

    marker_match = TITLE_STOP_PATTERN.search(normalized)
    if marker_match:
        cutoff = min(cutoff, marker_match.start())

    cleaned = normalized[:cutoff]
    cleaned = re.sub(r"\[[^\]]+\]|\([^)]+\)", " ", cleaned)
    cleaned = re.sub(r"\b(PROPER|REPACK|LIMITED)\b", " ", cleaned, flags=re.IGNORECASE)

    # Clean up
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" -:[]()")

    return cleaned if cleaned else normalized.split()[0] if normalized.split() else "Unknown"


def deduplicate_releases(releases: list[ParsedRelease]) -> list[ParsedRelease]:
    """Keep best quality version per title+year combination."""
    best: dict[str, ParsedRelease] = {}

    for release in releases:
        key = f"{release.title.lower().strip()}::{release.year or 'na'}"
        existing = best.get(key)

        if not existing or release.score > existing.score:
            best[key] = release

    return list(best.values())


def parse_and_deduplicate(raw_titles: list[str]) -> list[ParsedRelease]:
    """Parse multiple releases and return deduplicated best versions."""
    parsed = [parse_release(title) for title in raw_titles]
    return deduplicate_releases(parsed)
