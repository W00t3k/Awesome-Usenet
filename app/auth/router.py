"""Authentication API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.auth.dependencies import AuthenticatedUser
from app.auth.models import MigrateDataRequest, Token, UserCreate, UserLogin, UserPublic
from app.auth.utils import create_jwt, hash_password, verify_password

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])

# Will be set by main.py after initialization
_memory_store = None


def set_memory_store(store) -> None:  # noqa: ANN001
    """Set the memory store instance for auth operations."""
    global _memory_store
    _memory_store = store


def _get_store():
    """Get memory store or raise error."""
    if _memory_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth service not initialized",
        )
    return _memory_store


@auth_router.post("/register", response_model=Token)
async def register(payload: UserCreate) -> Token:
    """Register a new user account."""
    store = _get_store()

    # Check if username exists
    existing = store.get_user_by_username(payload.username)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken",
        )

    # Create user
    password_hash = hash_password(payload.password)
    user_id = store.create_user(
        username=payload.username,
        password_hash=password_hash,
        email=payload.email,
    )

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user",
        )

    # Generate token
    token = create_jwt(
        payload={
            "sub": user_id,
            "username": payload.username,
            "is_admin": False,
        },
        expires_in_seconds=86400 * 7,  # 7 days
    )

    return Token(access_token=token, token_type="bearer", expires_in=86400 * 7)


@auth_router.post("/login", response_model=Token)
async def login(payload: UserLogin) -> Token:
    """Login with username and password."""
    store = _get_store()

    user = store.get_user_by_username(payload.username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    # Generate token
    token = create_jwt(
        payload={
            "sub": user["id"],
            "username": user["username"],
            "is_admin": user["is_admin"],
        },
        expires_in_seconds=86400 * 7,
    )

    return Token(access_token=token, token_type="bearer", expires_in=86400 * 7)


@auth_router.get("/me", response_model=UserPublic)
async def get_me(user: AuthenticatedUser) -> UserPublic:
    """Get current user profile."""
    store = _get_store()

    user_data = store.get_user_by_id(user["user_id"])
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return UserPublic(
        id=user_data["id"],
        username=user_data["username"],
        email=user_data["email"],
        is_active=user_data["is_active"],
        is_admin=user_data["is_admin"],
        created_at=user_data["created_at"],
    )


@auth_router.post("/migrate-data")
async def migrate_data(
    payload: MigrateDataRequest,
    user: AuthenticatedUser,
) -> dict:
    """Migrate data from anonymous UUID to authenticated account."""
    store = _get_store()

    result = store.migrate_anonymous_data(
        anonymous_user_id=payload.anonymous_user_id,
        new_user_id=user["user_id"],
    )

    return {
        "ok": True,
        "message": "Data migrated successfully",
        **result,
    }
