"""Keeping the index healthy for years, not weeks.

- ``prune``: closed roles, old logs and caches would otherwise grow the free-tier
  database without bound.
- ``rediscover``: boards move (a company switches from Lever to Ashby) and new
  companies show up in the hiring threads and aggregators. Discovery runs on a
  schedule and writes new boards straight to the database, so coverage keeps up
  without anyone editing seed files.
- ``health``: one place that says whether crawling is actually working.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.ingest.discovery import Candidate, discover, load_candidates
from app.ingest.text import slugify
from app.models import Company, CompanySource, IngestRun, Interaction, Job, LLMCache, LLMCall

log = logging.getLogger(__name__)

CLOSED_JOB_DAYS = 180  # closed roles nobody acted on are deleted after this
CLOSED_VECTOR_DAYS = 30  # closed roles drop their embedding (the HNSW index) after this
IMPRESSION_DAYS = 365  # feed impressions kept for learning-to-rank
LOG_DAYS = 90  # ingest runs, LLM call logs and cached LLM answers
REPROBE_DAYS = 30
GLOBAL_KINDS = ("hn", "remotive", "arbeitnow", "remoteok")


def prune(session: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    acted_on = exists().where(Interaction.job_id == Job.id, Interaction.type != "impression")
    n_impr = session.execute(
        delete(Interaction).where(
            Interaction.type == "impression",
            Interaction.created_at < now - timedelta(days=IMPRESSION_DAYS),
        )
    ).rowcount
    n_jobs = session.execute(
        delete(Job).where(
            Job.status == "closed",
            Job.closed_at < now - timedelta(days=CLOSED_JOB_DAYS),
            ~acted_on,
        )
    ).rowcount
    n_vec = session.execute(
        update(Job)
        .where(
            Job.status == "closed",
            Job.closed_at < now - timedelta(days=CLOSED_VECTOR_DAYS),
            Job.embedding.is_not(None),
        )
        .values(embedding=None, embedded_hash=None)
    ).rowcount
    log_cut = now - timedelta(days=LOG_DAYS)
    n_runs = session.execute(delete(IngestRun).where(IngestRun.started_at < log_cut)).rowcount
    n_calls = session.execute(delete(LLMCall).where(LLMCall.created_at < log_cut)).rowcount
    n_cache = session.execute(delete(LLMCache).where(LLMCache.created_at < log_cut)).rowcount
    session.commit()
    return {
        "jobs_deleted": n_jobs,
        "vectors_dropped": n_vec,
        "impressions_deleted": n_impr,
        "ingest_runs_deleted": n_runs,
        "llm_calls_deleted": n_calls,
        "llm_cache_deleted": n_cache,
    }


def discovery_candidates(session: Session, now: datetime, limit: int) -> list[Candidate]:
    """Companies worth probing for their own ATS boards, most promising first.

    1. Lines added to seeds/candidates.txt that are not in the database yet.
    2. Companies whose boards all stopped working (moved ATS, renamed slug).
    3. Companies seen only through hiring threads or aggregators that have posted a
       tech role recently: if they have their own board, it is complete and fresher.
    Each company is probed at most once every REPROBE_DAYS.
    """
    due = or_(Company.probed_at.is_(None), Company.probed_at < now - timedelta(days=REPROBE_DAYS))
    known = set(session.scalars(select(Company.slug)))
    out: list[Candidate] = [c for c in load_candidates() if slugify(c.name) not in known]

    working = exists().where(
        CompanySource.company_id == Company.id,
        CompanySource.enabled.is_(True),
        CompanySource.consecutive_failures < 3,
        CompanySource.last_status.is_distinct_from("suspect"),
    )
    has_board = exists().where(CompanySource.company_id == Company.id)
    broken = session.scalars(select(Company).where(has_board, ~working, due)).all()
    recent_tech = (
        select(Job.company_id)
        .where(
            Job.is_tech.is_(True),
            Job.source_kind.in_(GLOBAL_KINDS),
            Job.first_seen_at > now - timedelta(days=60),
        )
        .group_by(Job.company_id)
        .order_by(func.count().desc())
    )
    unboarded = session.scalars(
        select(Company).where(Company.id.in_(recent_tech), ~has_board, due)
    ).all()
    for co in [*broken, *unboarded]:
        slugs = [s.key for s in co.sources if s.kind not in ("jsonld",) and "/" not in s.key]
        out.append(Candidate(name=co.name, slugs=slugs, careers_url=co.careers_url))
    return out[:limit]


def add_discovered(session: Session, results: list[dict], now: datetime) -> dict:
    added = probed = 0
    for r in results:
        slug = slugify(r["name"])[:200]
        co = session.scalar(select(Company).where(Company.slug == slug))
        if co is None:
            if not r["sources"]:
                continue
            co = Company(name=r["name"][:200], slug=slug, tags=r.get("tags") or [])
            session.add(co)
            session.flush()
        co.probed_at = now
        probed += 1
        for src in r["sources"]:
            if src["kind"] == "jsonld" and not src.get("jobs"):
                continue  # a careers page with no detectable board: nothing new to crawl
            row = session.scalar(
                select(CompanySource).where(
                    CompanySource.kind == src["kind"], CompanySource.key == src["key"]
                )
            )
            if row is None:
                session.add(CompanySource(company_id=co.id, kind=src["kind"], key=src["key"]))
                added += 1
            elif not row.enabled or row.consecutive_failures:
                row.enabled, row.consecutive_failures = True, 0  # the board is back
    session.commit()
    return {"probed": probed, "sources_added": added}


def rediscover(session: Session, limit: int = 150) -> dict:
    now = datetime.now(UTC)
    candidates = discovery_candidates(session, now, limit)
    if not candidates:
        return {"probed": 0, "sources_added": 0}
    results = asyncio.run(discover(candidates, concurrency=6))
    return add_discovered(session, results, now)


def health(session: Session, now: datetime | None = None) -> dict:
    """Is the index alive? Used by /api/health and the admin dashboard."""
    now = now or datetime.now(UTC)
    last_ok = session.scalar(select(func.max(IngestRun.finished_at)).where(IngestRun.ok))
    open_jobs = session.scalar(
        select(func.count()).select_from(Job).where(Job.status == "open", Job.is_tech)
    )
    failing = session.scalar(
        select(func.count())
        .select_from(CompanySource)
        .where(
            CompanySource.enabled.is_(True),
            or_(CompanySource.consecutive_failures >= 3, CompanySource.last_status == "suspect"),
        )
    )
    enabled = session.scalar(
        select(func.count()).select_from(CompanySource).where(CompanySource.enabled.is_(True))
    )
    fresh_24h = session.scalar(
        select(func.count())
        .select_from(Job)
        .where(and_(Job.status == "open", Job.is_tech, Job.first_seen_at > now - timedelta(days=1)))
    )
    hours = None if last_ok is None else round((now - last_ok).total_seconds() / 3600, 1)
    problems = []
    if hours is None or hours > 26:
        problems.append("no successful crawl in the last day")
    if enabled and failing / enabled > 0.25:
        problems.append(f"{failing} of {enabled} boards failing")
    if not open_jobs:
        problems.append("index is empty")
    return {
        "ok": not problems,
        "problems": problems,
        "hours_since_crawl": hours,
        "open_tech_jobs": open_jobs,
        "new_last_24h": fresh_24h,
        "boards_enabled": enabled,
        "boards_failing": failing,
    }
