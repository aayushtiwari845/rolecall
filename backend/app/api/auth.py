"""Google sign-in (OAuth 2.0 authorization code flow with PKCE) and session endpoints.

The web app proxies ``/api/*`` to this service, so the session cookie is first-party
on the web domain. A dev-only login exists for local testing without Google keys.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db
from app.config import get_settings
from app.core.security import create_token, decode_token, pkce_pair
from app.models import Preferences, User

router = APIRouter(prefix="/api/auth", tags=["auth"])

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_CERTS = "https://www.googleapis.com/oauth2/v3/certs"
OAUTH_COOKIE = "rolecall_oauth"
_jwks = jwt.PyJWKClient(GOOGLE_CERTS, cache_keys=True)


def _redirect_uri() -> str:
    return f"{get_settings().web_url.rstrip('/')}/api/auth/google/callback"


def _safe_next(path: str | None) -> str:
    return path if path and path.startswith("/") and not path.startswith("//") else "/feed"


def set_session(resp, user: User) -> None:
    s = get_settings()
    resp.set_cookie(
        s.session_cookie,
        create_token(str(user.id)),
        max_age=s.jwt_ttl_days * 86400,
        httponly=True,
        secure=not s.is_dev,
        samesite="lax",
        path="/",
    )


def upsert_user(
    db: Session, *, email: str, name: str | None, picture: str | None, sub: str | None
) -> User:
    s = get_settings()
    user = db.scalar(select(User).where(User.google_sub == sub)) if sub else None
    user = user or db.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        user = User(email=email.lower(), name=name, avatar_url=picture, google_sub=sub)
        user.preferences = Preferences()
        db.add(user)
    else:
        user.name = name or user.name
        user.avatar_url = picture or user.avatar_url
        user.google_sub = sub or user.google_sub
    user.is_admin = email.lower() in {e.lower() for e in s.admin_emails}
    db.commit()
    db.refresh(user)
    return user


@router.get("/google/login")
def google_login(next: str | None = None):
    s = get_settings()
    if not s.google_client_id:
        raise HTTPException(503, "Google sign-in is not configured on this server")
    state = secrets.token_urlsafe(24)
    verifier, challenge = pkce_pair()
    params = {
        "client_id": s.google_client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    resp = RedirectResponse(f"{GOOGLE_AUTH}?{urlencode(params)}", status_code=302)
    cookie = create_token(
        state, kind="oauth", ttl=timedelta(minutes=10), verifier=verifier, next=_safe_next(next)
    )
    resp.set_cookie(
        OAUTH_COOKIE,
        cookie,
        max_age=600,
        httponly=True,
        secure=not s.is_dev,
        samesite="lax",
        path="/",
    )
    return resp


@router.get("/google/callback")
def google_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    s = get_settings()
    web = s.web_url.rstrip("/")
    flow = decode_token(request.cookies.get(OAUTH_COOKIE, ""), kind="oauth")
    if error or not code or not flow or flow.get("sub") != state:
        return RedirectResponse(f"{web}/login?error=oauth", status_code=302)
    try:
        tok = httpx.post(
            GOOGLE_TOKEN,
            data={
                "code": code,
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "redirect_uri": _redirect_uri(),
                "grant_type": "authorization_code",
                "code_verifier": flow["verifier"],
            },
            timeout=15,
        ).json()
        id_token = tok["id_token"]
        key = _jwks.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            key.key,
            algorithms=["RS256"],
            audience=s.google_client_id,
            issuer=["https://accounts.google.com", "accounts.google.com"],
        )
    except (httpx.HTTPError, KeyError, jwt.PyJWTError):
        return RedirectResponse(f"{web}/login?error=oauth", status_code=302)
    if not claims.get("email_verified"):
        return RedirectResponse(f"{web}/login?error=unverified", status_code=302)
    user = upsert_user(
        db,
        email=claims["email"],
        name=claims.get("name"),
        picture=claims.get("picture"),
        sub=claims["sub"],
    )
    dest = flow.get("next") or "/feed"
    resp = RedirectResponse(f"{web}{dest if user.onboarded else '/onboarding'}", status_code=302)
    set_session(resp, user)
    resp.delete_cookie(OAUTH_COOKIE, path="/")
    return resp


class DevLogin(BaseModel):
    email: str = "dev@rolecall.local"
    name: str = "Dev User"


@router.post("/dev-login")
def dev_login(body: DevLogin, db: Session = Depends(get_db)):
    if not get_settings().is_dev:
        raise HTTPException(404)
    user = upsert_user(db, email=body.email, name=body.name, picture=None, sub=None)
    from fastapi.responses import JSONResponse

    resp = JSONResponse({"ok": True, "onboarded": user.onboarded})
    set_session(resp, user)
    return resp


@router.post("/logout")
def logout():
    from fastapi.responses import JSONResponse

    resp = JSONResponse({"ok": True})
    resp.delete_cookie(get_settings().session_cookie, path="/")
    return resp


@router.get("/config")
def auth_config():
    s = get_settings()
    return {"google": bool(s.google_client_id), "dev_login": s.is_dev}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "avatar_url": user.avatar_url,
        "is_admin": user.is_admin,
        "onboarded": user.onboarded,
    }
