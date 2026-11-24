"""Build a user's ranking context from their resume, preferences and behaviour.

Signals: saved/applied jobs (strong positive), clicks (weak positive), dismissals and
"less like this" (negative). They shape (1) the query vector, (2) a positive and a
negative centroid used for an affinity feature, and (3) per-company affinity.
"""

from __future__ import annotations

import uuid
from collections import Counter

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, Interaction, Job, Preferences, Resume, User
from app.search.filters import JobFilters
from app.search.rank import UserContext

POSITIVE = {"save": 1.0, "apply": 1.5, "more_like": 1.2, "click": 0.3}
NEGATIVE = {"dismiss": 1.0, "less_like": 1.2}


def _unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-9)


def active_resume(
    session: Session, user: User, resume_id: uuid.UUID | None = None
) -> Resume | None:
    q = select(Resume).where(Resume.user_id == user.id)
    if resume_id:
        r = session.scalar(q.where(Resume.id == resume_id))
        if r:
            return r
    return session.scalar(q.order_by(Resume.is_default.desc(), Resume.created_at.desc()))


def build_context(session: Session, user: User, resume_id: uuid.UUID | None = None) -> UserContext:
    prefs = user.preferences or Preferences(user_id=user.id)
    resume = active_resume(session, user, resume_id)
    profile = (resume.profile if resume else {}) or {}
    ctx = UserContext(
        skills=set((resume.skills if resume else []) or []),
        years=float(resume.years_experience if resume else 0),
        levels=list(prefs.seniorities or profile.get("suggested_seniorities") or []),
        families=list(prefs.role_families or profile.get("suggested_role_families") or []),
        cities=list(prefs.cities or []),
    )
    base = (
        np.asarray(resume.embedding, dtype=np.float32)
        if resume is not None and resume.embedding is not None
        else None
    )
    titles = profile.get("target_titles") or []
    ctx.lex_terms = [*titles[:5], *[s for s in (resume.skills if resume else [])[:12]]]

    rows = session.execute(
        select(Interaction.job_id, Interaction.type, Job.embedding, Job.company_name)
        .join(Job, Job.id == Interaction.job_id)
        .where(Interaction.user_id == user.id, Interaction.type.in_(list(POSITIVE | NEGATIVE)))
        .order_by(Interaction.created_at.desc())
        .limit(400)
    ).all()
    pos, neg, pos_w, neg_w = [], [], [], []
    company: Counter[str] = Counter()
    hidden: set[uuid.UUID] = set()
    for job_id, kind, emb, comp in rows:
        if kind in NEGATIVE:
            hidden.add(job_id)
            company[comp] -= 0.05 * NEGATIVE[kind]
            if emb is not None:
                neg.append(np.asarray(emb, dtype=np.float32))
                neg_w.append(NEGATIVE[kind])
        else:
            company[comp] += 0.04 * POSITIVE[kind]
            if emb is not None:
                pos.append(np.asarray(emb, dtype=np.float32))
                pos_w.append(POSITIVE[kind])
    saved = set(
        session.scalars(
            select(Application.job_id).where(
                Application.user_id == user.id, Application.job_id.is_not(None)
            )
        )
    )
    applied = set(
        session.scalars(
            select(Application.job_id).where(
                Application.user_id == user.id,
                Application.job_id.is_not(None),
                Application.status != "saved",
            )
        )
    )
    ctx.saved_job_ids = saved
    ctx.hidden_job_ids = list(hidden | applied)
    if pos:
        ctx.pos_centroid = _unit(np.average(np.stack(pos), axis=0, weights=pos_w))
    if neg:
        ctx.neg_centroid = _unit(np.average(np.stack(neg), axis=0, weights=neg_w))
    ctx.company_affinity = {k: max(-0.3, min(0.2, v)) for k, v in company.items()}

    if base is not None:
        q = base.copy()
        if ctx.pos_centroid is not None:
            q = 0.75 * q + 0.25 * ctx.pos_centroid
        if ctx.neg_centroid is not None:
            q = q - 0.1 * ctx.neg_centroid
        ctx.qvec = _unit(q)
    elif ctx.pos_centroid is not None:
        ctx.qvec = ctx.pos_centroid
    return ctx


def filters_from_prefs(prefs: Preferences | None, ctx: UserContext) -> JobFilters:
    if prefs is None:
        return JobFilters(seniorities=ctx.levels, role_families=_expand_families(ctx.families))
    return JobFilters(
        seniorities=list(prefs.seniorities or ctx.levels),
        role_families=_expand_families(list(prefs.role_families or [])),
        employment_types=list(prefs.employment_types or []),
        cities=list(prefs.cities or []),
        remote_india=prefs.remote_india,
        remote_global=prefs.remote_global,
        onsite_anywhere=prefs.onsite_global,
        exclude_companies=list(prefs.excluded_companies or []),
        min_salary_inr=prefs.min_salary_inr,
    )


def _expand_families(fams: list[str]) -> list[str]:
    """Generic SWE roles fit any engineering preference; full-stack fits backend/frontend."""
    if not fams:
        return []
    out = set(fams) | {"swe"}
    if {"backend", "frontend"} & out:
        out.add("fullstack")
    return sorted(out)
