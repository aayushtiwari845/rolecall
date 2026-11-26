"""Long-run upkeep: pruning, scheduled discovery, health."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

NOW = datetime(2027, 6, 1, tzinfo=UTC)


def _job(**kw):
    from app.models import Job

    base = dict(
        source_kind="greenhouse",
        source_job_id=f"mt-{uuid.uuid4().hex[:10]}",
        company_name="Acme",
        title="Backend Engineer",
        url="https://example.com/j",
        description_text="Python services.",
        status="open",
        is_tech=True,
        first_seen_at=NOW - timedelta(days=5),
        last_seen_at=NOW,
        posted_at=NOW - timedelta(days=5),
        content_hash="h",
        dedupe_key=uuid.uuid4().hex,
    )
    base.update(kw)
    return Job(**base)


def _clean(s):
    from app.models import Company, Job

    s.execute(delete(Job).where(Job.source_job_id.like("mt-%")))
    s.execute(delete(Company).where(Company.slug.like("mt-%")))
    s.commit()


def test_prune_keeps_roles_people_acted_on(db_url):
    from app.db import session_scope
    from app.ingest.maintenance import prune
    from app.models import Interaction, Job, User

    with session_scope() as s:
        _clean(s)
        old = NOW - timedelta(days=200)
        gone = _job(status="closed", closed_at=old)
        saved = _job(status="closed", closed_at=old)
        recent = _job(status="closed", closed_at=NOW - timedelta(days=40), embedding=[0.1] * 384)
        live = _job()
        s.add_all([gone, saved, recent, live])
        s.flush()
        user = User(email=f"mt-{uuid.uuid4().hex[:6]}@example.com", name="T")
        s.add(user)
        s.flush()
        s.add(Interaction(user_id=user.id, job_id=saved.id, type="save"))
        s.add(Interaction(user_id=user.id, job_id=gone.id, type="impression", created_at=NOW))
        s.commit()

        out = prune(s, now=NOW)
        ids = set(s.scalars(select(Job.id).where(Job.source_job_id.like("mt-%"))))
        assert gone.id not in ids  # closed long ago, only ever shown
        assert {saved.id, recent.id, live.id} <= ids
        s.refresh(recent)
        assert recent.embedding is None and out["vectors_dropped"] >= 1
        s.delete(user)
        _clean(s)


def test_discovery_targets_aggregator_only_and_broken_companies(db_url):
    from app.db import session_scope
    from app.ingest.maintenance import add_discovered, discovery_candidates
    from app.models import Company, CompanySource

    with session_scope() as s:
        _clean(s)
        hn_only = Company(name="mt-hn-only", slug="mt-hn-only", tags=[])
        broken = Company(name="mt-broken", slug="mt-broken", tags=[])
        healthy = Company(name="mt-healthy", slug="mt-healthy", tags=[])
        s.add_all([hn_only, broken, healthy])
        s.flush()
        s.add(_job(source_kind="hn", company_id=hn_only.id, first_seen_at=NOW - timedelta(days=3)))
        s.add(CompanySource(company_id=broken.id, kind="lever", key="mt-broken", enabled=False))
        s.add(CompanySource(company_id=healthy.id, kind="ashby", key="mt-healthy"))
        s.commit()

        names = {c.name for c in discovery_candidates(s, NOW, limit=10_000)}
        assert {"mt-hn-only", "mt-broken"} <= names and "mt-healthy" not in names

        res = add_discovered(
            s,
            [
                {"name": "mt-hn-only", "sources": [{"kind": "greenhouse", "key": "mt-hn", "jobs": 4}]},
                {"name": "mt-broken", "sources": []},
            ],
            NOW,
        )
        assert res == {"probed": 2, "sources_added": 1}
        # Probed companies wait REPROBE_DAYS before being probed again.
        names = {c.name for c in discovery_candidates(s, NOW + timedelta(days=1), limit=10_000)}
        assert "mt-hn-only" not in names and "mt-broken" not in names
        s.execute(delete(CompanySource).where(CompanySource.key.like("mt-%")))
        _clean(s)


def test_health_flags_a_stalled_crawl(db_url):
    from app.db import session_scope
    from app.ingest.maintenance import health
    from app.models import IngestRun

    with session_scope() as s:
        s.add(IngestRun(kind="greenhouse", ok=True, finished_at=NOW - timedelta(hours=2)))
        s.commit()
        assert health(s, now=NOW)["hours_since_crawl"] == 2.0
        stalled = health(s, now=NOW + timedelta(days=3))
        assert not stalled["ok"] and "no successful crawl in the last day" in stalled["problems"]
