"""Session tokens (HS256 JWT in an HttpOnly cookie) and small signing helpers."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from app.config import get_settings


def create_token(
    subject: str, *, kind: str = "session", ttl: timedelta | None = None, **claims
) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "kind": kind,
        "iat": int(now.timestamp()),
        "exp": int((now + (ttl or timedelta(days=s.jwt_ttl_days))).timestamp()),
        **claims,
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_token(token: str, *, kind: str = "session") -> dict | None:
    try:
        data = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return data if data.get("kind") == kind else None


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge
