"""Recommendation, search and similar-jobs entry points used by the API, agent and alerts."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
import time
import uuid

import numpy as np
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enrich.embed import embed_query, rerank
from app.enrich.locations import parse_location
from app.ingest.text import display_title
from app.models import Job
from app.search.filters import JobFilters, build_where
from app.search.rank import (
    Ranked,
    UserContext,
    Weights,
    diversify,
    finalize,
    load_config,
    score_candidates,
)
from app.search.retrieval import Candidate, hybrid, lexical_query

log = logging.getLogger(__name__)

_CACHE_TTL = 300
_cache: dict[str, tuple[float, list[tuple[uuid.UUID, float, int]]]] = {}
_cache_lock = threading.Lock()


def _load_jobs(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, Job]:
    if not ids:
        return {}
    return {j.id: j for j in session.scalars(select(Job).where(Job.id.in_(ids)))}


def _fresh_candidates(
    session: Session, filters: JobFilters, k: int, exclude=None
) -> list[Candidate]:
    """Cold start: with no resume and no history there is nothing to match against, so
    start from the newest roles inside the user's filters."""
    rows = session.execute(
        select(Job.id)
        .where(*build_where(filters, exclude))
        .order_by(Job.posted_at.desc().nulls_last(), Job.id)
        .limit(k)
    ).all()
    return [Candidate(job_id=r.id) for r in rows]


def _relaxations(f: JobFilters) -> list[tuple[str, JobFilters]]:
    """Ordered ways to widen too-narrow preferences, least surprising first."""
    steps: list[tuple[str, JobFilters]] = []
    cur = f
    if cur.cities and not cur.onsite_anywhere:
        cur = cur.model_copy(
            update={"cities": [], "remote_india": True, "remote_global": True, "countries": ["IN"]}
        )
        steps.append(("anywhere in India or remote", cur))
    if cur.role_families:
        cur = cur.model_copy(update={"role_families": []})
        steps.append(("any kind of engineering role", cur))
    if cur.posted_within_days:
        cur = cur.model_copy(update={"posted_within_days": None})
        steps.append(("older postings", cur))
    return steps


def _retrieve(
    session: Session, user: UserContext, filters: JobFilters, w: Weights, mode: str
) -> list[Candidate]:
    exclude = user.hidden_job_ids or None
    lex = lexical_query(user.lex_terms)
    if user.qvec is None and not lex:
        return _fresh_candidates(session, filters, w.k_dense, exclude)
    try:
        return hybrid(
            session,
            qvec=user.qvec,
            lex_query=lex,
            filters=filters,
            k_dense=w.k_dense,
            k_lex=w.k_lex,
            exclude=exclude,
            mode=mode,
            rrf_k=w.rrf_k,
            w_dense=w.w_dense,
            w_lex=w.w_lex,
        )
    except OperationalError:
        # Timeout or transient DB error on the vector query: degrade to fresh roles.
        session.rollback()
        log.warning("hybrid retrieval failed; falling back to fresh roles", exc_info=True)
        return _fresh_candidates(session, filters, w.k_dense, exclude)


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
    relax: bool = True,
) -> list[Ranked]:
    """Personalised feed for a profile.

    If the preferences match fewer than ``min_results`` roles, they are widened step by
    step (cities, then role kinds, then freshness) and every widened-in role says so.
    """
    w = weights or load_config()
    key = None
    if cache_key:
        key = f"{cache_key}:{hashlib.sha1(filters.model_dump_json().encode()).hexdigest()}"
        with _cache_lock:
            hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < _CACHE_TTL and offset > 0:
            return _rehydrate(session, user, hit[1][offset : offset + limit], w)

    cands = _retrieve(session, user, filters, w, mode)
    jobs = _load_jobs(session, [c.job_id for c in cands])
    ranked = finalize(score_candidates(cands, jobs, user, w), w)

    if relax and len(ranked) < w.min_results:
        seen = {r.job.id for r in ranked}
        for label, wider in _relaxations(filters):
            extra = [c for c in _retrieve(session, user, wider, w, mode) if c.job_id not in seen]
            if not extra:
                continue
            more = score_candidates(extra, _load_jobs(session, [c.job_id for c in extra]), user, w)
            for r in more:
                r.warnings.insert(0, f"Outside your preferences: {label}")
            ranked += finalize(more, w)
            seen |= {r.job.id for r in more}
            if len(ranked) >= w.min_results:
                break

    if key:
        with _cache_lock:
            _cache[key] = (time.monotonic(), [(r.job.id, r.score, r.match) for r in ranked])
            if len(_cache) > 500:
                _cache.pop(next(iter(_cache)))
    return ranked[offset : offset + limit]


def _rehydrate(session: Session, user: UserContext, rows, w: Weights) -> list[Ranked]:
    # Re-score just the requested page so reasons are present; order comes from the cache.
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


_QUERY_REMOTE = re.compile(r"\bremote(?:ly)?\b|\bwfh\b|work from home", re.I)


def query_location(query: str, filters: JobFilters) -> JobFilters | None:
    """Places named in the query become a location filter when none is set.

    "RAG intern Bengaluru" means roles in Bengaluru (or remote roles open to India),
    not internships in Bangkok that happen to mention RAG. Returns None when the query
    names no place or the user already chose locations.
    """
    if not query or not filters.is_location_free() or filters.onsite_anywhere:
        return None
    place = parse_location(query)
    remote = bool(_QUERY_REMOTE.search(query))
    if not (place.cities or place.countries or remote):
        return None
    update: dict = {}
    if place.cities:
        update["cities"] = place.cities
        update["remote_india"] = True
    elif place.countries:
        update["countries"] = place.countries
    if remote:
        update["remote_india"] = True
        update["remote_global"] = not place.countries or "IN" in place.countries
    return filters.model_copy(update=update)


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
    placed = query_location(" ".join(query.split())[:300], filters)
    if placed is not None:
        found = search(
            session,
            query,
            placed,
            user=user,
            limit=limit,
            offset=offset,
            use_rerank=use_rerank,
            mode=mode,
        )
        if found or offset:
            return found
        # Nothing there: fall back to the query without the place filter.
    return _search(
        session,
        query,
        filters,
        user=user,
        limit=limit,
        offset=offset,
        use_rerank=use_rerank,
        mode=mode,
    )


def _search(
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
    user = user or UserContext()
    cfg = load_config()
    query = " ".join(query.split())[:300]
    qvec = user.qvec
    if query:
        try:
            qvec = embed_query(query)
        except Exception:  # noqa: BLE001 - model unavailable: keyword search still works
            log.warning("query embedding failed; lexical only", exc_info=True)
            qvec, mode = None, "lexical"
    lex = query if query else lexical_query(user.lex_terms)
    try:
        cands = hybrid(
            session,
            qvec=qvec,
            lex_query=lex,
            filters=filters,
            k_dense=150,
            k_lex=150,
            mode=mode,
            rrf_k=cfg.rrf_k,
            w_dense=cfg.w_dense,
            w_lex=cfg.w_lex,
        )
    except OperationalError:
        session.rollback()
        log.warning("search retrieval failed", exc_info=True)
        return []
    if not cands:
        return []
    jobs = _load_jobs(session, [c.job_id for c in cands[:200]])
    cands = [c for c in cands if c.job_id in jobs]
    top_rrf = max(c.rrf for c in cands) or 1.0
    relevance = {c.job_id: c.rrf / top_rrf for c in cands}

    do_rerank = get_settings().rerank_enabled if use_rerank is None else use_rerank
    head_n, blend = cfg.rerank_head, cfg.rerank_blend
    if use_rerank and not head_n:
        # Asked for explicitly (evals, a faster host) while the released config has it off.
        head_n, blend = Weights().rerank_head, Weights().rerank_blend
    if do_rerank and query and head_n:
        head = cands[:head_n]
        docs = [
            f"{jobs[c.job_id].title} at {jobs[c.job_id].company_name}. "
            f"{' '.join((jobs[c.job_id].skills or [])[:10])}. {(jobs[c.job_id].description_text or '')[:400]}"
            for c in head
        ]
        try:
            scores = rerank(query, docs)
        except Exception:  # noqa: BLE001 - reranker unavailable: keep fused order
            log.warning("rerank failed", exc_info=True)
            scores = []
        if scores:
            b = blend
            for c, sc in zip(head, scores, strict=True):
                relevance[c.job_id] = (1 - b) * relevance[c.job_id] + b * _sigmoid(sc)
            for c in cands[head_n:]:
                relevance[c.job_id] *= 1 - b  # below the reranked head

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
