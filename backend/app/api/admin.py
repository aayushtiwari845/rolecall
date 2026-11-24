"""Admin metrics: index health, ingestion, engagement funnel, LLM usage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import Date, Integer, cast, func, select
from sqlalchemy.orm import Session

from app.api.deps import admin_user, get_db
from app.models import (
    Application,
    CompanySource,
    IngestRun,
    Interaction,
    Job,
    LLMCall,
    Resume,
    User,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/metrics")
def metrics(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    d1, d7, d30 = now - timedelta(days=1), now - timedelta(days=7), now - timedelta(days=30)
    open_jobs = (Job.status == "open", Job.is_tech.is_(True), Job.duplicate_of.is_(None))

    def count(model, *where):
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    def events(kind: str, since):
        return count(Interaction, Interaction.type == kind, Interaction.created_at >= since)

    impressions = events("impression", d7)
    clicks = events("click", d7)
    saves = events("save", d7)
    applies = events("apply", d7)

    daily = db.execute(
        select(
            cast(Interaction.created_at, Date).label("day"),
            func.count(func.distinct(Interaction.user_id)),
        )
        .where(Interaction.created_at >= d30)
        .group_by("day")
        .order_by("day")
    ).all()
    ingest_daily = db.execute(
        select(cast(Job.first_seen_at, Date).label("day"), func.count())
        .where(Job.first_seen_at >= d30, Job.is_tech.is_(True))
        .group_by("day")
        .order_by("day")
    ).all()
    sources = db.execute(
        select(
            CompanySource.kind,
            CompanySource.last_status,
            func.count(),
            func.sum(CompanySource.jobs_open),
        ).group_by(CompanySource.kind, CompanySource.last_status)
    ).all()
    failing = db.execute(
        select(
            CompanySource.kind,
            CompanySource.key,
            CompanySource.last_error,
            CompanySource.consecutive_failures,
        )
        .where(CompanySource.last_status == "error")
        .order_by(CompanySource.consecutive_failures.desc())
        .limit(15)
    ).all()
    runs = db.execute(
        select(
            IngestRun.kind,
            func.count(),
            func.sum(IngestRun.created),
            func.sum(IngestRun.closed),
            func.avg(func.extract("epoch", IngestRun.finished_at - IngestRun.started_at)),
        )
        .where(IngestRun.started_at >= d1)
        .group_by(IngestRun.kind)
    ).all()
    llm = db.execute(
        select(
            LLMCall.provider,
            LLMCall.purpose,
            func.count(),
            func.sum(cast(LLMCall.ok, Integer)),
            func.sum(LLMCall.prompt_tokens + LLMCall.completion_tokens),
            func.avg(LLMCall.latency_ms),
            func.sum(cast(LLMCall.cache_hit, Integer)),
        )
        .where(LLMCall.created_at >= d7)
        .group_by(LLMCall.provider, LLMCall.purpose)
    ).all()

    return {
        "index": {
            "open_jobs": count(Job, *open_jobs),
            "embedded": count(Job, *open_jobs, Job.embedding.is_not(None)),
            "llm_enriched": count(Job, *open_jobs, Job.enriched_by == "rules+llm"),
            "duplicates": count(Job, Job.status == "open", Job.duplicate_of.is_not(None)),
            "closed_last_7d": count(Job, Job.closed_at >= d7),
            "new_last_24h": count(Job, *open_jobs, Job.first_seen_at >= d1),
        },
        "users": {
            "total": count(User),
            "new_7d": count(User, User.created_at >= d7),
            "active_1d": count(User, User.last_seen_at >= d1),
            "active_7d": count(User, User.last_seen_at >= d7),
            "with_resume": db.scalar(select(func.count(func.distinct(Resume.user_id)))) or 0,
            "tracked_applications": count(Application),
        },
        "funnel_7d": {
            "impressions": impressions,
            "clicks": clicks,
            "saves": saves,
            "applies": applies,
            "ctr": round(clicks / impressions, 4) if impressions else None,
            "save_rate": round(saves / impressions, 4) if impressions else None,
            "dismissals": events("dismiss", d7),
        },
        "daily_active": [{"day": str(d), "users": n} for d, n in daily],
        "daily_new_jobs": [{"day": str(d), "jobs": n} for d, n in ingest_daily],
        "sources": [
            {"kind": k, "status": s, "count": n, "open_jobs": int(o or 0)} for k, s, n, o in sources
        ],
        "failing_sources": [
            {"kind": k, "key": key, "error": (e or "")[:200], "failures": f}
            for k, key, e, f in failing
        ],
        "ingest_24h": [
            {
                "kind": k,
                "runs": n,
                "created": int(c or 0),
                "closed": int(cl or 0),
                "avg_seconds": round(float(s or 0), 1),
            }
            for k, n, c, cl, s in runs
        ],
        "llm_7d": [
            {
                "provider": p,
                "purpose": pu,
                "calls": n,
                "ok": int(ok or 0),
                "tokens": int(t or 0),
                "avg_latency_ms": int(lat or 0),
                "cache_hits": int(ch or 0),
            }
            for p, pu, n, ok, t, lat, ch in llm
        ],
    }
