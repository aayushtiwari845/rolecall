"""Recommendation, search and similar-jobs entry points used by the API, agent and alerts."""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
import uuid

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enrich.embed import embed_query, rerank
from app.ingest.text import display_title
from app.models import Job
from app.search.filters import JobFilters
from app.search.rank import Ranked, UserContext, Weights, diversify, score_candidates
from app.search.retrieval import hybrid, lexical_query

_CACHE_TTL = 300
_cache: dict[str, tuple[float, list[tuple[uuid.UUID, float, int]]]] = {}
_cache_lock = threading.Lock()


def _load_jobs(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, Job]:
    if not ids:
        return {}
    return {j.id: j for j in session.scalars(select(Job).where(Job.id.in_(ids)))}


def recommend(
    session: Session,
    user: UserContext,
    filters: JobFilters,
    *,
    limit: int = 20,
    offset: int = 0,
    weights: Weights | None = None,
    cache_key: str | None = None,
    mode: str = "hybrid",
) -> list[Ranked]:
    """Personalised feed for a profile."""
    w = weights or Weights()
    key = None
    if cache_key:
        key = f"{cache_key}:{hashlib.sha1(filters.model_dump_json().encode()).hexdigest()}"
        with _cache_lock:
            hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < _CACHE_TTL and offset > 0:
            return _rehydrate(session, user, hit[1][offset : offset + limit], w)

    cands = hybrid(
        session,
        qvec=user.qvec,
        lex_query=lexical_query(user.lex_terms),
        filters=filters,
        k_dense=300,
        k_lex=150,
        exclude=user.hidden_job_ids or None,
        mode=mode,
    )
    jobs = _load_jobs(session, [c.job_id for c in cands])
    ranked = score_candidates(cands, jobs, user, w)
    if w.diversify:
        ranked = diversify(ranked, w.max_per_company)
    if key:
        with _cache_lock:
            _cache[key] = (time.monotonic(), [(r.job.id, r.score, r.match) for r in ranked])
            if len(_cache) > 500:
                _cache.pop(next(iter(_cache)))
    return ranked[offset : offset + limit]


def _rehydrate(session: Session, user: UserContext, rows, w: Weights) -> list[Ranked]:
    # Re-score just the requested page so reasons are present; order comes from the cache.
    from app.search.retrieval import Candidate

    jobs = _load_jobs(session, [r[0] for r in rows])
    cands = [Candidate(job_id=r[0], dense_rank=1, dense_sim=r[1]) for r in rows]
    scored = {r.job.id: r for r in score_candidates(cands, jobs, user, w)}
    out = []
    for jid, score, match in rows:
        if jid in scored:
            r = scored[jid]
            r.score, r.match = score, match
            out.append(r)
    return out


def invalidate_user(user_key: str) -> None:
    """Drop cached feeds for a user (after feedback, preference or resume changes)."""
    with _cache_lock:
        for k in list(_cache):
            if k.startswith(f"{user_key}:"):
                _cache.pop(k, None)


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def search(
    session: Session,
    query: str,
    filters: JobFilters,
    *,
    user: UserContext | None = None,
    limit: int = 20,
    offset: int = 0,
    use_rerank: bool | None = None,
    mode: str = "hybrid",
) -> list[Ranked]:
    """Free-text search with optional personalisation."""
    user = user or UserContext()
    query = query.strip()
    qvec = embed_query(query) if query else user.qvec
    lex = query if query else lexical_query(user.lex_terms)
    cands = hybrid(
        session, qvec=qvec, lex_query=lex, filters=filters, k_dense=150, k_lex=150, mode=mode
    )
    if not cands:
        return []
    jobs = _load_jobs(session, [c.job_id for c in cands[:200]])
    cands = [c for c in cands if c.job_id in jobs]
    top_rrf = max(c.rrf for c in cands) or 1.0
    relevance = {c.job_id: c.rrf / top_rrf for c in cands}

    do_rerank = get_settings().rerank_enabled if use_rerank is None else use_rerank
    if do_rerank and query:
        head = cands[:40]
        docs = [
            f"{jobs[c.job_id].title} at {jobs[c.job_id].company_name}. "
            f"{' '.join((jobs[c.job_id].skills or [])[:10])}. {(jobs[c.job_id].description_text or '')[:400]}"
            for c in head
        ]
        scores = rerank(query, docs)
        for c, s in zip(head, scores, strict=True):
            relevance[c.job_id] = 0.35 * relevance[c.job_id] + 0.65 * _sigmoid(s)
        for c in cands[40:]:
            relevance[c.job_id] *= 0.35  # below the reranked head

    personal = user.qvec is not None or bool(user.skills)
    w = Weights(
        semantic=0.7,
        lexical=0.0,
        skills=0.1 if personal else 0.0,
        level=0.07 if personal else 0.0,
        role=0.0,
        location=0.03,
        recency=0.07,
        affinity=0.03 if personal else 0.0,
        diversify=False,
    )
    ranked = score_candidates(cands, jobs, user, w, relevance=relevance)
    return ranked[offset : offset + limit]


def similar(
    session: Session, job_id: uuid.UUID, *, limit: int = 8, user: UserContext | None = None
) -> list[Ranked]:
    job = session.get(Job, job_id)
    if job is None or job.embedding is None:
        return []
    qvec = np.asarray(job.embedding, dtype=np.float32)
    f = JobFilters()
    cands = hybrid(
        session,
        qvec=qvec,
        lex_query="",
        filters=f,
        k_dense=limit * 4,
        k_lex=0,
        exclude=[job_id],
        mode="dense",
    )
    jobs = _load_jobs(session, [c.job_id for c in cands])
    ranked = score_candidates(
        cands,
        jobs,
        user or UserContext(),
        Weights(
            semantic=0.8,
            skills=0.1 if user else 0,
            level=0.1 if user else 0,
            lexical=0,
            role=0,
            location=0,
            recency=0.1,
            affinity=0,
        ),
    )
    return diversify(ranked, 2, window=limit)[:limit]


def ranked_to_dict(r: Ranked) -> dict:
    j = r.job
    return {
        "id": str(j.id),
        "title": display_title(j.title),
        "company": j.company_name,
        "url": j.url,
        "location": j.location_raw,
        "cities": j.cities or [],
        "remote_type": j.remote_type,
        "seniority": j.seniority,
        "role_family": j.role_family,
        "employment_type": j.employment_type,
        "skills": (j.skills or [])[:12],
        "posted_at": j.posted_at.isoformat() if j.posted_at else None,
        "salary": _salary(j),
        "source": j.source_kind,
        "match": r.match,
        "reasons": r.reasons,
        "warnings": r.warnings,
        "matched_skills": r.matched_skills,
        "missing_skills": r.missing_skills,
        "features": {k: round(v, 3) for k, v in r.features.items()},
        "weights": r.weights,
    }


def _salary(j: Job) -> dict | None:
    if j.salary_min is None and j.salary_max is None:
        return None
    return {
        "min": j.salary_min,
        "max": j.salary_max,
        "currency": j.salary_currency,
        "period": j.salary_period,
    }


def dumps(items: list[Ranked]) -> str:
    return json.dumps([ranked_to_dict(r) for r in items])
