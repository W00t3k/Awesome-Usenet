"""Authentication API routes."""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.auth.dependencies import AuthenticatedUser
from app.auth.models import MigrateDataRequest, Token, UserCreate, UserLogin, UserPublic
from app.auth.utils import create_jwt, hash_password, verify_password
from app.config import settings

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])

# Google OAuth configuration
GOOGLE_CLIENT_ID = getattr(settings, "google_client_id", None) or ""
GOOGLE_CLIENT_SECRET = getattr(settings, "google_client_secret", None) or ""
GOOGLE_REDIRECT_URI = getattr(settings, "google_redirect_uri", None) or "http://127.0.0.1:8080/api/auth/google/callback"

# OAuth state storage (in production, use Redis or similar)
_oauth_states: dict[str, dict] = {}

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


# ============================================================================
# Google OAuth Endpoints
# ============================================================================

@auth_router.get("/google/enabled")
async def google_oauth_enabled() -> dict:
    """Check if Google OAuth is configured."""
    return {
        "enabled": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
    }


@auth_router.get("/google/login")
async def google_login(redirect_to: str = "/") -> RedirectResponse:
    """Initiate Google OAuth flow."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured",
        )

    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"redirect_to": redirect_to}

    # Build Google OAuth URL
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    }
    google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    return RedirectResponse(url=google_auth_url)


@auth_router.get("/google/callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    """Handle Google OAuth callback."""
    # Verify state
    if state not in _oauth_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state",
        )

    state_data = _oauth_states.pop(state)
    redirect_to = state_data.get("redirect_to", "/")

    # Exchange code for tokens
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": GOOGLE_REDIRECT_URI,
            },
        )

        if token_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange OAuth code",
            )

        tokens = token_response.json()
        access_token = tokens.get("access_token")

        # Get user info from Google
        userinfo_response = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if userinfo_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to get user info from Google",
            )

        google_user = userinfo_response.json()

    # Extract user info
    google_id = google_user.get("id")
    email = google_user.get("email")
    name = google_user.get("name", email.split("@")[0] if email else "User")

    store = _get_store()

    # Check if user exists by Google ID or email
    user = store.get_user_by_google_id(google_id)
    if not user and email:
        user = store.get_user_by_email(email)

    if user:
        # Existing user - update Google ID if needed
        if not user.get("google_id"):
            store.update_user_google_id(user["id"], google_id)
        user_id = user["id"]
        username = user["username"]
        is_admin = user["is_admin"]
    else:
        # Create new user
        username = email.split("@")[0] if email else f"user_{google_id[:8]}"
        # Ensure unique username
        base_username = username
        counter = 1
        while store.get_user_by_username(username):
            username = f"{base_username}{counter}"
            counter += 1

        user_id = store.create_user(
            username=username,
            password_hash="",  # No password for OAuth users
            email=email,
            google_id=google_id,
        )
        is_admin = False

    # Generate JWT token
    jwt_token = create_jwt(
        payload={
            "sub": user_id,
            "username": username,
            "is_admin": is_admin,
        },
        expires_in_seconds=86400 * 7,
    )

    # Redirect with token (frontend will store it)
    redirect_url = f"{redirect_to}?token={jwt_token}"
    return RedirectResponse(url=redirect_url)
