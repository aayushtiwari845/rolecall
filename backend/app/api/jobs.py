"""Feed, search, job detail, similar jobs, AI match explanations, facets and public stats."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db, optional_user, rate_limit
from app.llm.router import LLMError, get_llm
from app.models import Company, CompanySource, Interaction, Job, User
from app.search.engine import ranked_to_dict, recommend, search, similar
from app.search.filters import JobFilters
from app.search.personalize import build_context, filters_from_prefs
from app.search.rank import UserContext, score_candidates
from app.search.retrieval import Candidate

router = APIRouter(prefix="/api", tags=["jobs"])


class FeedRequest(BaseModel):
    resume_id: uuid.UUID | None = None
    filters: JobFilters | None = None  # overrides saved preferences when given
    limit: int = 20
    offset: int = 0


def _log_impressions(
    db: Session,
    user: User | None,
    items: list[dict],
    surface: str,
    offset: int,
    query: str | None = None,
):
    if user is None or not items:
        return
    db.add_all(
        [
            Interaction(
                user_id=user.id,
                job_id=uuid.UUID(it["id"]),
                type="impression",
                surface=surface,
                position=offset + i,
                query=query,
            )
            for i, it in enumerate(items)
        ]
    )
    db.commit()


@router.post("/feed")
def feed(
    body: FeedRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    _rl=Depends(rate_limit("feed", 120, 40)),
):
    ctx = build_context(db, user, body.resume_id)
    filters = body.filters or filters_from_prefs(user.preferences, ctx)
    items = recommend(
        db,
        ctx,
        filters,
        limit=min(body.limit, 50),
        offset=body.offset,
        cache_key=f"{user.id}:{body.resume_id}",
    )
    out = [ranked_to_dict(r) | {"saved": r.job.id in ctx.saved_job_ids} for r in items]
    _log_impressions(db, user, out, "feed", body.offset)
    return {"items": out, "filters": filters.model_dump(), "has_profile": ctx.qvec is not None}


class SearchRequest(BaseModel):
    q: str = ""
    filters: JobFilters = JobFilters()
    personalize: bool = True
    resume_id: uuid.UUID | None = None
    limit: int = 20
    offset: int = 0


@router.post("/search")
def search_jobs(
    body: SearchRequest,
    user: User | None = Depends(optional_user),
    db: Session = Depends(get_db),
    _rl=Depends(rate_limit("search", 90, 30)),
):
    ctx = build_context(db, user, body.resume_id) if (user and body.personalize) else None
    items = search(
        db, body.q[:300], body.filters, user=ctx, limit=min(body.limit, 50), offset=body.offset
    )
    saved = ctx.saved_job_ids if ctx else set()
    out = [ranked_to_dict(r) | {"saved": r.job.id in saved} for r in items]
    _log_impressions(db, user, out, "search", body.offset, body.q)
    return {"items": out}


def _job_detail(job: Job) -> dict:
    return {
        "id": str(job.id),
        "title": job.title,
        "company": job.company_name,
        "url": job.url,
        "apply_url": job.apply_url or job.url,
        "location": job.location_raw,
        "cities": job.cities,
        "countries": [c for c in job.countries or [] if not c.startswith("R:")],
        "remote_type": job.remote_type,
        "seniority": job.seniority,
        "role_family": job.role_family,
        "employment_type": job.employment_type,
        "skills": job.skills,
        "min_yoe": job.min_yoe,
        "max_yoe": job.max_yoe,
        "salary": None
        if job.salary_min is None and job.salary_max is None
        else {
            "min": job.salary_min,
            "max": job.salary_max,
            "currency": job.salary_currency,
            "period": job.salary_period,
        },
        "summary": job.summary,
        "description": job.description_text,
        "department": job.department,
        "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        "first_seen_at": job.first_seen_at.isoformat() if job.first_seen_at else None,
        "status": job.status,
        "source": job.source_kind,
    }


@router.get("/jobs/{job_id}")
def get_job(
    job_id: uuid.UUID, user: User | None = Depends(optional_user), db: Session = Depends(get_db)
):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    out = _job_detail(job)
    if user:
        ctx = build_context(db, user)
        [r] = score_candidates([Candidate(job_id=job.id)], {job.id: job}, ctx, _detail_weights())
        out["match"] = ranked_to_dict(r)
        out["saved"] = job.id in ctx.saved_job_ids
        db.add(Interaction(user_id=user.id, job_id=job.id, type="click", surface="job"))
        db.commit()
    return out


def _detail_weights():
    from app.search.rank import Weights

    # No retrieval scores on a direct view: rely on the profile features only.
    return Weights(
        semantic=0.0,
        lexical=0.0,
        skills=0.4,
        level=0.25,
        role=0.15,
        location=0.1,
        recency=0.05,
        affinity=0.05,
    )


@router.get("/jobs/{job_id}/similar")
def similar_jobs(
    job_id: uuid.UUID, user: User | None = Depends(optional_user), db: Session = Depends(get_db)
):
    ctx = build_context(db, user) if user else None
    return {"items": [ranked_to_dict(r) for r in similar(db, job_id, limit=8, user=ctx)]}


class MatchExplanation(BaseModel):
    verdict: str
    strengths: list[str]
    gaps: list[str]
    tips: list[str]


@router.post("/jobs/{job_id}/explain")
def explain_match(
    job_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    _rl=Depends(rate_limit("explain", 10, 5)),
):
    """LLM-written fit analysis of the user's resume against a job (cached per resume+job)."""
    from app.search.personalize import active_resume

    job = db.get(Job, job_id)
    resume = active_resume(db, user)
    if job is None or resume is None:
        raise HTTPException(404, "Need a job and a resume")
    llm = get_llm()
    if not llm.available:
        raise HTTPException(503, "AI explanations are not configured on this server")
    prompt = (
        "You are a candid career coach for students and early-career engineers. Compare the candidate to the job. "
        "verdict: one sentence on overall fit. strengths: up to 4 specific matches, citing resume evidence. "
        "gaps: up to 3 honest gaps. tips: up to 3 concrete things to highlight or do before applying.\n\n"
        f"JOB: {job.title} at {job.company_name} ({job.location_raw})\n{(job.description_text or '')[:3500]}\n\n"
        f"CANDIDATE RESUME:\n{resume.text[:3500]}"
    )
    try:
        res = llm.structured(
            [{"role": "user", "content": prompt}], MatchExplanation, tier="smart", purpose="explain"
        )
    except LLMError as e:
        raise HTTPException(503, f"AI is busy right now, try again in a minute ({e})") from e
    return res.model_dump()


@router.get("/facets")
def facets(db: Session = Depends(get_db)):
    base = (Job.status == "open", Job.is_tech.is_(True), Job.duplicate_of.is_(None))

    def count_by(col):
        return [
            {"value": k, "count": v}
            for k, v in db.execute(
                select(col, func.count())
                .where(*base, col.is_not(None))
                .group_by(col)
                .order_by(func.count().desc())
            ).all()
        ]

    city = func.unnest(Job.cities).label("city")
    cities = db.execute(
        select(city, func.count())
        .where(*base)
        .group_by(city)
        .order_by(func.count().desc())
        .limit(40)
    ).all()
    companies = db.execute(
        select(Job.company_name, func.count())
        .where(*base)
        .group_by(Job.company_name)
        .order_by(func.count().desc())
        .limit(300)
    ).all()
    return {
        "seniority": count_by(Job.seniority),
        "role_family": count_by(Job.role_family),
        "employment_type": count_by(Job.employment_type),
        "remote_type": count_by(Job.remote_type),
        "cities": [{"value": k, "count": v} for k, v in cities],
        "companies": [{"value": k, "count": v} for k, v in companies],
    }


@router.get("/stats")
def public_stats(db: Session = Depends(get_db)):
    base = (Job.status == "open", Job.is_tech.is_(True), Job.duplicate_of.is_(None))
    day = datetime.now(UTC) - timedelta(days=1)
    week = datetime.now(UTC) - timedelta(days=7)
    india = (
        db.scalar(select(func.count()).select_from(Job).where(*base, Job.countries.any("IN"))) or 0
    )
    early = (
        db.scalar(
            select(func.count())
            .select_from(Job)
            .where(*base, Job.seniority.in_(["intern", "new_grad", "junior"]))
        )
        or 0
    )
    return {
        "open_jobs": db.scalar(select(func.count()).select_from(Job).where(*base)) or 0,
        "new_today": db.scalar(
            select(func.count()).select_from(Job).where(*base, Job.first_seen_at >= day)
        )
        or 0,
        "new_this_week": db.scalar(
            select(func.count()).select_from(Job).where(*base, Job.first_seen_at >= week)
        )
        or 0,
        "india_jobs": india,
        "early_career_jobs": early,
        "companies": db.scalar(select(func.count(func.distinct(Job.company_id))).where(*base)) or 0,
        "sources": db.scalar(
            select(func.count()).select_from(CompanySource).where(CompanySource.enabled.is_(True))
        )
        or 0,
        "last_crawl": (
            db.scalar(select(func.max(CompanySource.last_run_at))) or datetime.now(UTC)
        ).isoformat(),
        "users": db.scalar(select(func.count()).select_from(User)) or 0,
        "tracked_companies": db.scalar(select(func.count()).select_from(Company)) or 0,
    }


@router.get("/companies/{name}/jobs")
def company_jobs(name: str, limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    jobs = list(
        db.scalars(
            select(Job)
            .where(
                Job.company_name == name,
                Job.status == "open",
                Job.is_tech.is_(True),
                Job.duplicate_of.is_(None),
            )
            .order_by(Job.posted_at.desc().nulls_last())
            .limit(limit)
        )
    )
    ctx = UserContext()
    return {
        "items": [
            ranked_to_dict(r)
            for r in score_candidates(
                [Candidate(job_id=j.id) for j in jobs],
                {j.id: j for j in jobs},
                ctx,
                _detail_weights(),
            )
        ]
    }
