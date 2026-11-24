"""Shared FastAPI dependencies: database session, authentication, rate limiting."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.security import decode_token
from app.db import get_db
from app.models import User

__all__ = ["get_db", "current_user", "optional_user", "admin_user", "rate_limit"]


def _token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return request.cookies.get(get_settings().session_cookie)


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = _token(request)
    if not token:
        return None
    data = decode_token(token)
    if not data:
        return None
    try:
        user = db.get(User, uuid.UUID(data["sub"]))
    except (ValueError, KeyError):
        return None
    if user is not None:
        now = datetime.now(UTC)
        if not user.last_seen_at or now - user.last_seen_at > timedelta(minutes=10):
            user.last_seen_at = now
            db.commit()
    return user


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admins only")
    return user


class _Bucket:
    """Tiny in-memory token bucket per key. Good enough for a single API instance."""

    def __init__(self) -> None:
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, rate_per_min: float, burst: float) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._state.get(key, (burst, now))
            tokens = min(burst, tokens + (now - last) * rate_per_min / 60)
            if tokens < 1:
                self._state[key] = (tokens, now)
                return False
            self._state[key] = (tokens - 1, now)
            if len(self._state) > 50_000:
                self._state.clear()
            return True


_bucket = _Bucket()


def rate_limit(name: str, per_min: float = 60, burst: float = 30):
    def dep(request: Request, user: User | None = Depends(optional_user)) -> None:
        who = str(user.id) if user else (request.client.host if request.client else "anon")
        if not _bucket.allow(f"{name}:{who}", per_min, burst):
            raise HTTPException(status_code=429, detail="Slow down a little")

    return dep
