from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MovieCandidate(BaseModel):
    movie_id: str
    title: str
    year: int | None = None
    release_date: str | None = None
    genres: list[str] = Field(default_factory=list)
    overview: str | None = None
    source_tags: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    available_on_plex: bool = False
    available_on_radarr: bool = False
    available_on_usenet: bool = False


class AgentResult(BaseModel):
    agent: str
    status: str
    runtime_ms: int
    item_count: int = 0
    notes: str | None = None


class RecommendationReason(BaseModel):
    label: str
    value: float
    detail: str


class Recommendation(BaseModel):
    movie: MovieCandidate
    score: float
    reasons: list[RecommendationReason]


class RecommendationResponse(BaseModel):
    generated_at: datetime
    user_id: str
    recommendations: list[Recommendation]
    agents: list[AgentResult]


class FeedbackInput(BaseModel):
    user_id: str = "default"
    movie_id: str
    title: str
    liked: bool
    note: str | None = None
    genres: list[str] = Field(default_factory=list)
    year: int | None = None
    overview: str | None = None


class FeedbackRow(BaseModel):
    id: int
    user_id: str
    movie_id: str
    title: str
    liked: bool
    note: str | None = None
    genres: list[str] = Field(default_factory=list)
    year: int | None = None
    created_at: str


class AgentContext(BaseModel):
    user_id: str
    requested_count: int
    now_iso: str


class SourcePayload(BaseModel):
    movies: list[MovieCandidate] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
