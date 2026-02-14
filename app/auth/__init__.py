"""Authentication module for Majic Movie Selector."""

from app.auth.router import auth_router
from app.auth.dependencies import get_current_user, require_auth, require_admin
from app.auth.utils import hash_password, verify_password, create_jwt, verify_jwt

__all__ = [
    "auth_router",
    "get_current_user",
    "require_auth",
    "require_admin",
    "hash_password",
    "verify_password",
    "create_jwt",
    "verify_jwt",
]
