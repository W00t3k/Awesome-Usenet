"""Authentication utilities using standard library (no external deps)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)
_runtime_jwt_secret: str | None = None


def _get_jwt_secret() -> str:
    """Get JWT secret from settings or generate a per-process random secret."""
    secret = (getattr(settings, "jwt_secret", None) or "").strip()
    if secret:
        return secret

    global _runtime_jwt_secret
    if _runtime_jwt_secret is None:
        _runtime_jwt_secret = secrets.token_urlsafe(64)
        logger.warning(
            "JWT_SECRET is not configured. Using an ephemeral runtime secret; "
            "tokens will be invalidated on restart."
        )
    return _runtime_jwt_secret


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Hash password using PBKDF2 with SHA256.

    Returns format: salt$hash (both base64 encoded)
    """
    if salt is None:
        salt = os.urandom(32)

    dk = hashlib.pbkdf2_hmac(
        hash_name="sha256",
        password=password.encode("utf-8"),
        salt=salt,
        iterations=100_000,
        dklen=32,
    )

    salt_b64 = base64.b64encode(salt).decode("ascii")
    hash_b64 = base64.b64encode(dk).decode("ascii")
    return f"{salt_b64}${hash_b64}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against stored hash."""
    try:
        salt_b64, stored_hash_b64 = password_hash.split("$")
        salt = base64.b64decode(salt_b64)
        stored_hash = base64.b64decode(stored_hash_b64)

        dk = hashlib.pbkdf2_hmac(
            hash_name="sha256",
            password=password.encode("utf-8"),
            salt=salt,
            iterations=100_000,
            dklen=32,
        )

        return hmac.compare_digest(dk, stored_hash)
    except (ValueError, TypeError):
        return False


def _base64url_encode(data: bytes) -> str:
    """URL-safe base64 encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(data: str) -> bytes:
    """URL-safe base64 decode with padding restoration."""
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


def create_jwt(
    payload: dict[str, Any],
    expires_in_seconds: int = 86400 * 7,  # 7 days default
) -> str:
    """Create a simple JWT token using HMAC-SHA256.

    Args:
        payload: Claims to include in the token
        expires_in_seconds: Token expiry time

    Returns:
        JWT token string
    """
    secret = _get_jwt_secret()

    # Header
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _base64url_encode(json.dumps(header).encode())

    # Payload with expiry
    now = int(time.time())
    claims = {
        **payload,
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    payload_b64 = _base64url_encode(json.dumps(claims).encode())

    # Signature
    message = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature_b64 = _base64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def verify_jwt(token: str) -> dict[str, Any] | None:
    """Verify and decode a JWT token.

    Args:
        token: JWT token string

    Returns:
        Decoded payload if valid, None otherwise
    """
    secret = _get_jwt_secret()

    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, signature_b64 = parts

        # Verify signature
        message = f"{header_b64}.{payload_b64}"
        expected_signature = hmac.new(
            secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        actual_signature = _base64url_decode(signature_b64)

        if not hmac.compare_digest(expected_signature, actual_signature):
            return None

        # Decode payload
        payload_json = _base64url_decode(payload_b64).decode("utf-8")
        payload = json.loads(payload_json)

        # Check expiry
        exp = payload.get("exp")
        if exp and int(time.time()) > exp:
            return None

        return payload

    except (ValueError, TypeError, json.JSONDecodeError, KeyError):
        return None
