"""FastAPI dependencies for authentication."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.auth.utils import verify_jwt


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> dict | None:
    """Extract current user from Authorization header.

    Returns None if no valid token provided (anonymous access allowed).
    """
    if not authorization:
        return None

    # Support "Bearer <token>" format
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    token = parts[1]
    payload = verify_jwt(token)
    if not payload:
        return None

    return {
        "user_id": payload.get("sub"),
        "username": payload.get("username"),
        "is_admin": payload.get("is_admin", False),
    }


async def require_auth(
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Require valid authentication.

    Raises HTTPException 401 if not authenticated.
    """
    user = await get_current_user(authorization)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_admin(
    user: Annotated[dict, Depends(require_auth)],
) -> dict:
    """Require admin privileges.

    Raises HTTPException 403 if not admin.
    """
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user


# Type aliases for cleaner endpoint signatures
CurrentUser = Annotated[dict | None, Depends(get_current_user)]
AuthenticatedUser = Annotated[dict, Depends(require_auth)]
AdminUser = Annotated[dict, Depends(require_admin)]
