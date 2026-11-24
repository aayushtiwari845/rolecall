"""FastAPI application."""

from __future__ import annotations

import logging
import threading
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import admin, alerts, auth, chat, jobs, profile, public, tracker
from app.config import get_settings

log = logging.getLogger("rolecall")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="Rolecall API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json"
)

settings = get_settings()
if settings.is_dev:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_EXEMPT = {"/api/auth/google/callback"}


@app.middleware("http")
async def csrf_and_timing(request: Request, call_next):
    """Cookie-authenticated writes must carry a custom header, which cross-site forms
    cannot set without a CORS preflight that we never grant."""
    if (
        request.method not in SAFE_METHODS
        and request.url.path not in CSRF_EXEMPT
        and request.cookies.get(settings.session_cookie)
        and request.headers.get("x-rolecall") != "1"
    ):
        return JSONResponse({"detail": "missing X-Rolecall header"}, status_code=403)
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - started) * 1000:.1f}"
    return response


for r in (
    auth.router,
    jobs.router,
    profile.router,
    tracker.router,
    alerts.router,
    chat.router,
    admin.router,
    public.router,
):
    app.include_router(r)


@app.get("/api/health")
def health():
    from sqlalchemy import text

    from app.db import session_scope

    with session_scope() as s:
        s.execute(text("select 1"))
    return {"ok": True}


@app.on_event("startup")
def warm_models() -> None:
    """Load the embedding model in the background so the first search isn't slow."""

    def _warm():
        try:
            from app.enrich.embed import embed_query

            embed_query("warm up")
        except Exception:  # noqa: BLE001
            log.exception("model warm-up failed")

    threading.Thread(target=_warm, daemon=True).start()
