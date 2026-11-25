"""Shared fixtures. DB tests use TEST_DATABASE_URL (default: the local compose test DB)
and are skipped when Postgres is not reachable."""

from __future__ import annotations

import hashlib
import os

import numpy as np
import pytest
from sqlalchemy import create_engine, text

TEST_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://rolecall:rolecall@localhost:5433/rolecall_test"
)


def fake_vec(text_: str) -> np.ndarray:
    """Deterministic bag-of-words vector, so similar texts land close together."""
    v = np.zeros(384, dtype=np.float32)
    for w in text_.lower().split():
        h = int(hashlib.md5(w.strip(".,:;()").encode()).hexdigest(), 16)
        v[h % 384] += 1.0
    n = np.linalg.norm(v)
    return v / n if n else v


@pytest.fixture(scope="session")
def db_url():
    try:
        eng = create_engine(TEST_URL)
        with eng.connect() as c:
            c.execute(text("select 1"))
    except Exception:  # noqa: BLE001
        pytest.skip("test Postgres not available")
    from app.db import Base, reset_engine

    reset_engine(TEST_URL)
    with eng.begin() as c:
        c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        c.execute(
            text(
                "CREATE OR REPLACE FUNCTION rc_join(text[]) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE "
                "AS $$ SELECT array_to_string($1, ' ') $$"
            )
        )
    import app.models  # noqa: F401

    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield TEST_URL
    Base.metadata.drop_all(eng)


@pytest.fixture()
def client(db_url, monkeypatch):
    from fastapi.testclient import TestClient

    import app.api.profile as profile
    import app.api.public as public
    import app.search.engine as engine
    from app.llm.router import LLMRouter, set_llm

    fake_q = lambda t: fake_vec(t)  # noqa: E731
    monkeypatch.setattr(engine, "embed_query", fake_q)
    monkeypatch.setattr(profile, "embed_query", fake_q)
    monkeypatch.setattr(public, "embed_query", fake_q)
    monkeypatch.setattr(engine, "rerank", lambda q, docs: [0.0] * len(docs))
    set_llm(LLMRouter(providers=[], record=False))

    from app.main import app

    with TestClient(app) as c:
        c.headers["X-Rolecall"] = "1"
        yield c
    set_llm(None)
