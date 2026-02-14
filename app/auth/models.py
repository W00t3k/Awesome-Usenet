"""Pydantic models for authentication."""

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    """Request model for user registration."""

    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=100)
    email: str | None = None


class UserLogin(BaseModel):
    """Request model for user login."""

    username: str
    password: str


class Token(BaseModel):
    """Response model for authentication token."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserPublic(BaseModel):
    """Public user information (no password)."""

    id: int
    username: str
    email: str | None = None
    is_active: bool = True
    is_admin: bool = False
    created_at: str


class MigrateDataRequest(BaseModel):
    """Request to migrate anonymous user data to authenticated account."""

    anonymous_user_id: str = Field(
        description="The anonymous UUID (from localStorage) to migrate data from"
    )
