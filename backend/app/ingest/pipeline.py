"""Ingestion pipeline: fetch -> enrich (rules) -> dedupe -> upsert -> close stale.

Fetching is concurrent (async, polite client); database writes happen sequentially in
the event loop thread as each source finishes, so a slow source never blocks the rest.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.enrich.rules import RULES_VERSION, enrich
from app.ingest.discovery import load_seeds
from app.ingest.http import FetchError, PoliteClient
from app.ingest.sources import ADAPTERS, AGGREGATOR_KINDS
from app.ingest.text import norm_company, norm_title, sha, slugify
from app.ingest.types import FetchResult, RawJob
from app.models import Company, CompanySource, IngestRun, Job

log = logging.getLogger(__name__)

# Sources that are not tied to a single company.
GLOBAL_SOURCES = [("hn", "latest"), ("remotive", ""), ("arbeitnow", ""), ("remoteok", "")]
# Prefer company-owned boards over aggregators when the same role appears twice.
SOURCE_PRIORITY = {
    "greenhouse": 0,
    "lever": 0,
    "ashby": 0,
    "workable": 0,
    "smartrecruiters": 0,
    "recruitee": 0,
    "workday": 0,
    "jsonld": 1,
    "hn": 2,
    "remotive": 3,
    "arbeitnow": 3,
    "remoteok": 3,
}
PARTIAL_STALE_DAYS = 7
AUTO_DISABLE_AFTER = 5
# A complete board listing under this share of its open roles is not trusted for closing.
SUSPICIOUS_DROP_RATIO = 0.2


@dataclass
class RunStats:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    closed: int = 0
    skipped_non_tech: int = 0
    suspect: bool = False


def seed_sources(session: Session) -> int:
    """Load seeds/companies.yaml (+ global sources) into companies/company_sources."""
    n = 0
    for entry in load_seeds():
        slug = slugify(entry["name"])
        company = session.scalar(select(Company).where(Company.slug == slug))
        if company is None:
            company = Company(name=entry["name"], slug=slug, tags=entry.get("tags") or [])
            session.add(company)
            session.flush()
        else:
            company.tags = entry.get("tags") or company.tags
        for src in entry.get("sources") or []:
            exists = session.scalar(
                select(CompanySource).where(
                    CompanySource.kind == src["kind"], CompanySource.key == src["key"]
                )
            )
            if exists is None:
                session.add(CompanySource(company_id=company.id, kind=src["kind"], key=src["key"]))
                n += 1
            if src["kind"] == "jsonld":
                company.careers_url = src["key"]
    for kind, key in GLOBAL_SOURCES:
        if not session.scalar(
            select(CompanySource).where(CompanySource.kind == kind, CompanySource.key == key)
        ):
            session.add(CompanySource(company_id=None, kind=kind, key=key))
            n += 1
    session.commit()
    return n


def _company_for(session: Session, name: str, cache: dict[str, int]) -> int:
    slug = slugify(name)[:200]
    if slug in cache:
        return cache[slug]
    cid = session.scalar(select(Company.id).where(Company.slug == slug))
    if cid is None:
        company = Company(name=name[:200], slug=slug, tags=[])
        session.add(company)
        session.flush()
        cid = company.id
    cache[slug] = cid
    return cid


def dedupe_key(raw: RawJob, cities: list[str], countries: list[str]) -> str:
    """Same company + same title + same place = same role (e.g. one req per office)."""
    place = cities[0] if cities else ",".join(sorted(countries))
    return sha(norm_company(raw.company_name), norm_title(raw.title), place)[:64]


def upsert_jobs(session: Session, source: CompanySource, result: FetchResult) -> RunStats:
    stats = RunStats(fetched=len(result.jobs))
    now = datetime.now(UTC)
    company_cache: dict[str, int] = {}
    seen_ids: set[str] = set()

    existing = {
        j.source_job_id: j
        for j in session.scalars(
            select(Job).where(Job.source_kind == source.kind, Job.source_id == source.id)
        )
    }
    was_open = sum(1 for j in existing.values() if j.status == "open")

    for raw in result.jobs:
        if not raw.title or not raw.url:
            continue
        seen_ids.add(raw.source_job_id)
        content_hash = sha(raw.title, raw.description_text, raw.location_raw)
        job = existing.get(raw.source_job_id)
        if job is not None:
            job.last_seen_at = now
            job.missed_runs = 0
            if job.status != "open":
                job.status, job.closed_at = "open", None
            if job.content_hash == content_hash and job.enrichment_version >= RULES_VERSION:
                continue
        e = enrich(raw)
        if not e.is_tech:
            if job is None:
                stats.skipped_non_tech += 1
            else:
                job.is_tech = False
            continue
        if job is None:
            # Same posting id may exist from an older source row; fall back to global key.
            job = session.scalar(
                select(Job).where(
                    Job.source_kind == raw.source_kind, Job.source_job_id == raw.source_job_id
                )
            )
        is_new = job is None
        # Resolve the company before touching the Job so autoflush never sees a half-built row.
        company_id = source.company_id or _company_for(session, raw.company_name, company_cache)
        if is_new:
            job = Job(
                source_kind=raw.source_kind, source_job_id=raw.source_job_id, first_seen_at=now
            )
        job.source_id = source.id
        job.company_id = company_id
        job.company_name = (source.company.name if source.company else raw.company_name)[:200]
        job.title = raw.title[:400]
        job.url = raw.url
        job.apply_url = raw.apply_url
        job.location_raw = raw.location_raw
        job.department = (raw.department or "")[:300] or None
        job.description_text = raw.description_text[:60000]
        job.posted_at = raw.posted_at or job.posted_at or now
        job.last_seen_at = now
        job.status, job.closed_at, job.missed_runs = "open", None, 0
        job.content_hash = content_hash
        job.dedupe_key = dedupe_key(raw, e.cities, e.countries)
        job.is_tech = e.is_tech
        job.seniority = e.seniority
        job.role_family = e.role_family
        job.employment_type = e.employment_type
        job.remote_type = e.remote_type
        job.cities = e.cities
        job.countries = e.countries
        job.skills = e.skills
        job.min_yoe, job.max_yoe = e.min_yoe, e.max_yoe
        job.salary_min, job.salary_max = e.salary_min, e.salary_max
        job.salary_currency, job.salary_period = e.salary_currency, e.salary_period
        job.enrichment_version = RULES_VERSION
        job.enriched_by = "rules"
        if is_new:
            session.add(job)
            stats.created += 1
        else:
            stats.updated += 1

    session.flush()
    if result.complete:
        if suspicious_drop(was_open, len(seen_ids)):
            # A board that suddenly lists nothing, or a fraction of what it had, has
            # usually changed its API or is failing, not filled every role overnight.
            stats.suspect = True
            log.warning(
                "%s:%s listed %d jobs (had %d open); not closing any",
                source.kind,
                source.key,
                len(seen_ids),
                was_open,
            )
        else:
            stats.closed += _close_missing(session, source, seen_ids, now)
    return stats


def suspicious_drop(was_open: int, listed: int) -> bool:
    """True when a complete board's listing shrank too much to trust for closing jobs."""
    if was_open < 5:
        return False
    return listed == 0 or listed < was_open * SUSPICIOUS_DROP_RATIO


def _close_missing(session: Session, source: CompanySource, seen: set[str], now: datetime) -> int:
    """Complete boards: a job missing from N consecutive runs has been filled/removed."""
    limit = get_settings().close_after_missed_runs
    closed = 0
    for job in session.scalars(select(Job).where(Job.source_id == source.id, Job.status == "open")):
        if job.source_job_id in seen:
            continue
        job.missed_runs += 1
        if job.missed_runs >= limit:
            job.status, job.closed_at = "closed", now
            closed += 1
    return closed


def close_stale(session: Session) -> int:
    """Partial sources (aggregators, crawled pages, Workday search) expire by age."""
    now = datetime.now(UTC)
    ttl = get_settings().aggregator_ttl_days
    partial = list(AGGREGATOR_KINDS | {"jsonld", "workday"})
    q1 = (
        update(Job)
        .where(
            Job.status == "open",
            Job.source_kind.in_(partial),
            Job.last_seen_at < now - timedelta(days=PARTIAL_STALE_DAYS),
        )
        .values(status="closed", closed_at=now)
    )
    q2 = (
        update(Job)
        .where(
            Job.status == "open",
            Job.source_kind.in_(list(AGGREGATOR_KINDS)),
            Job.posted_at < now - timedelta(days=ttl),
        )
        .values(status="closed", closed_at=now)
    )
    n = session.execute(q1).rowcount + session.execute(q2).rowcount
    session.commit()
    return n


def mark_duplicates(session: Session) -> int:
    """Link open jobs that share a dedupe key to a single canonical posting.

    Canonical = company-owned board over aggregators, then the earliest seen.
    """
    from sqlalchemy import text

    sql = text(
        """
        WITH ranked AS (
          SELECT id, dedupe_key,
                 first_value(id) OVER (
                   PARTITION BY dedupe_key
                   ORDER BY CASE source_kind
                     WHEN 'hn' THEN 2 WHEN 'jsonld' THEN 1
                     WHEN 'remotive' THEN 3 WHEN 'arbeitnow' THEN 3 WHEN 'remoteok' THEN 3
                     ELSE 0 END,
                   first_seen_at
                 ) AS canonical
          FROM jobs WHERE status = 'open' AND is_tech
        )
        UPDATE jobs j SET duplicate_of = CASE WHEN r.canonical = j.id THEN NULL ELSE r.canonical END
        FROM ranked r
        WHERE j.id = r.id
          AND j.duplicate_of IS DISTINCT FROM (CASE WHEN r.canonical = j.id THEN NULL ELSE r.canonical END)
        """
    )
    n = session.execute(sql).rowcount
    session.commit()
    return n


async def _fetch(client: PoliteClient, source: CompanySource) -> FetchResult:
    adapter = ADAPTERS[source.kind]
    name = source.company.name if source.company else None
    return await adapter(client, source.key, name)


async def run_ingest(
    kinds: list[str] | None = None,
    limit: int | None = None,
    source_ids: list[int] | None = None,
    stale_hours: float | None = None,
) -> dict:
    """Crawl enabled sources. ``stale_hours`` skips sources crawled more recently."""
    with session_scope() as session:
        q = select(CompanySource).where(CompanySource.enabled.is_(True))
        if kinds:
            q = q.where(CompanySource.kind.in_(kinds))
        if source_ids:
            q = q.where(CompanySource.id.in_(source_ids))
        if stale_hours:
            cutoff = datetime.now(UTC) - timedelta(hours=stale_hours)
            q = q.where(
                (CompanySource.last_run_at.is_(None)) | (CompanySource.last_run_at < cutoff)
            )
        q = q.order_by(CompanySource.last_run_at.asc().nulls_first())
        if limit:
            q = q.limit(limit)
        source_ids = [s.id for s in session.scalars(q)]

    totals = RunStats()
    failures = suspects = 0
    client = PoliteClient()

    async def one(sid: int) -> tuple[int, FetchResult | Exception]:
        with session_scope() as s:
            src = s.get(CompanySource, sid)
            assert src is not None
            _ = src.company  # load the relationship before the session closes
            s.expunge(src)
        try:
            return sid, await _fetch(client, src)
        except Exception as e:  # noqa: BLE001 - recorded per source
            return sid, e

    try:
        tasks = [asyncio.create_task(one(sid)) for sid in source_ids]
        for fut in asyncio.as_completed(tasks):
            sid, result = await fut
            with session_scope() as session:
                src = session.get(CompanySource, sid)
                assert src is not None
                run = IngestRun(source_id=sid, kind=src.kind)
                session.add(run)
                src.last_run_at = datetime.now(UTC)
                if isinstance(result, Exception):
                    failures += 1
                    msg = str(result)[:1000]
                    run.ok, run.error = False, msg
                    src.last_status, src.last_error = "error", msg
                    src.consecutive_failures += 1
                    # Boards that 404 repeatedly have moved; stop hammering them.
                    if (
                        isinstance(result, FetchError)
                        and result.status == 404
                        and src.consecutive_failures >= AUTO_DISABLE_AFTER
                    ):
                        src.enabled = False
                    log.warning("source %s:%s failed: %s", src.kind, src.key, msg)
                else:
                    st = upsert_jobs(session, src, result)
                    run.fetched, run.created, run.updated = st.fetched, st.created, st.updated
                    run.closed, run.skipped_non_tech = st.closed, st.skipped_non_tech
                    src.last_status, src.last_error, src.consecutive_failures = "ok", None, 0
                    if st.suspect:
                        suspects += 1
                        src.last_status = "suspect"
                        src.last_error = f"listed {st.fetched} jobs, far fewer than before"
                        run.error = src.last_error
                    for k in ("fetched", "created", "updated", "closed", "skipped_non_tech"):
                        setattr(totals, k, getattr(totals, k) + getattr(st, k))
                run.finished_at = datetime.now(UTC)
                session.flush()
                from sqlalchemy import func

                src.jobs_open = (
                    session.scalar(
                        select(func.count())
                        .select_from(Job)
                        .where(Job.source_id == sid, Job.status == "open", Job.is_tech)
                    )
                    or 0
                )
    finally:
        await client.aclose()

    with session_scope() as session:
        stale = close_stale(session)
        dupes = mark_duplicates(session)
    return {
        "sources": len(source_ids),
        "failures": failures,
        "suspect_sources": suspects,
        **{k: v for k, v in totals.__dict__.items() if k != "suspect"},
        "closed_stale": stale,
        "dedupe_updates": dupes,
    }


def ingest(**kw) -> dict:
    return asyncio.run(run_ingest(**kw))
