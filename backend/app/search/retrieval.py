"""First-stage candidate generation: dense (pgvector) + lexical (Postgres FTS), fused with RRF.

Dense retrieval catches paraphrases ("ML infra" ~ "model serving platform"); lexical
retrieval catches exact terms embeddings blur (library names, "SDE 1", company names).
Reciprocal Rank Fusion combines the two rankings without needing comparable scores.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Job
from app.search.filters import JobFilters, build_where

RRF_K = 60


@dataclass
class Candidate:
    job_id: uuid.UUID
    dense_rank: int | None = None
    lex_rank: int | None = None
    dense_sim: float = 0.0
    lex_score: float = 0.0
    rrf: float = 0.0
    extra: dict = field(default_factory=dict)


def _tune(session: Session) -> None:
    # Iterative HNSW scans keep filtered vector queries from returning too few rows.
    try:
        session.execute(text("SET LOCAL hnsw.ef_search = 200"))
        session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        # A runaway query must never hang a request; callers fall back on timeout.
        session.execute(text("SET LOCAL statement_timeout = '4s'"))
    except Exception:  # noqa: BLE001 - older pgvector: fine without it
        session.rollback()


def dense(
    session: Session, qvec: np.ndarray, filters: JobFilters, k: int, exclude=None
) -> list[tuple[uuid.UUID, float]]:
    _tune(session)
    dist = Job.embedding.cosine_distance(qvec.tolist())
    q = (
        select(Job.id, (1 - dist).label("sim"))
        .where(*build_where(filters, exclude), Job.embedding.is_not(None))
        .order_by(dist)
        .limit(k)
    )
    return [(r.id, float(r.sim)) for r in session.execute(q)]


_TERM_CLEAN = re.compile(r"[^\w+#. -]")


def lexical_query(terms: list[str]) -> str:
    """Build a websearch_to_tsquery string that ORs phrases together."""
    out = []
    for t in terms:
        t = _TERM_CLEAN.sub(" ", t).strip()
        if t:
            out.append(f'"{t}"' if " " in t else t)
    return " OR ".join(out)


def lexical(
    session: Session, query: str, filters: JobFilters, k: int, exclude=None
) -> list[tuple[uuid.UUID, float]]:
    if not query.strip():
        return []
    tsq = func.websearch_to_tsquery("english", query)
    rank = func.ts_rank_cd(Job.search_tsv, tsq, 32)
    q = (
        select(Job.id, rank.label("score"))
        .where(*build_where(filters, exclude), Job.search_tsv.op("@@")(tsq))
        .order_by(rank.desc())
        .limit(k)
    )
    return [(r.id, float(r.score)) for r in session.execute(q)]


def fuse(
    dense_hits: list[tuple[uuid.UUID, float]],
    lex_hits: list[tuple[uuid.UUID, float]],
    w_dense: float = 1.0,
    w_lex: float = 1.0,
    rrf_k: int = RRF_K,
) -> list[Candidate]:
    cands: dict[uuid.UUID, Candidate] = {}
    for rank, (jid, sim) in enumerate(dense_hits, 1):
        c = cands.setdefault(jid, Candidate(jid))
        c.dense_rank, c.dense_sim = rank, sim
        c.rrf += w_dense / (rrf_k + rank)
    for rank, (jid, score) in enumerate(lex_hits, 1):
        c = cands.setdefault(jid, Candidate(jid))
        c.lex_rank, c.lex_score = rank, score
        c.rrf += w_lex / (rrf_k + rank)
    return sorted(cands.values(), key=lambda c: c.rrf, reverse=True)


def hybrid(
    session: Session,
    *,
    qvec: np.ndarray | None,
    lex_query: str,
    filters: JobFilters,
    k_dense: int = 200,
    k_lex: int = 150,
    exclude=None,
    mode: str = "hybrid",
    rrf_k: int = RRF_K,
    w_dense: float = 1.0,
    w_lex: float = 1.0,
) -> list[Candidate]:
    d = (
        dense(session, qvec, filters, k_dense, exclude)
        if (qvec is not None and mode in ("hybrid", "dense"))
        else []
    )
    lx = (
        lexical(session, lex_query, filters, k_lex, exclude)
        if mode in ("hybrid", "lexical")
        else []
    )
    return fuse(d, lx, w_dense, w_lex, rrf_k)
