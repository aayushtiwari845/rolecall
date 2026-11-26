"""Ingestion safety: a board that suddenly lists nothing must not close its roles."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, func, select

from app.ingest.pipeline import suspicious_drop, upsert_jobs
from app.ingest.types import FetchResult, RawJob


@pytest.mark.parametrize(
    "was_open,listed,expected",
    [
        (0, 0, False),  # a new or empty board
        (3, 0, False),  # too small to judge
        (40, 0, True),
        (40, 5, True),
        (40, 30, False),
        (10, 2, False),  # exactly 20% is a plausible clear-out
    ],
)
def test_suspicious_drop(was_open, listed, expected):
    assert suspicious_drop(was_open, listed) is expected


def _jobs(n: int) -> list[RawJob]:
    return [
        RawJob(
            source_kind="greenhouse",
            source_job_id=f"pipe-{i}",
            company_name="Acme",
            title=f"Backend Engineer {i}",
            url=f"https://example.com/{i}",
            location_raw="Bengaluru, India",
            description_text="Build Python and PostgreSQL services for payments. " * 4,
        )
        for i in range(n)
    ]


def test_an_emptied_board_keeps_its_roles_open(db_url):
    from app.db import session_scope
    from app.models import CompanySource, Job

    with session_scope() as s:
        s.execute(delete(Job).where(Job.source_job_id.like("pipe-%")))
        src = CompanySource(kind="greenhouse", key="acme-pipeline-test")
        s.add(src)
        s.flush()
        upsert_jobs(s, src, FetchResult(jobs=_jobs(10), complete=True))
        s.flush()

        def open_count() -> int:
            return s.scalar(
                select(func.count()).where(Job.source_id == src.id, Job.status == "open")
            )

        assert open_count() == 10
        for _ in range(3):  # an API change that returns an empty list, run after run
            st = upsert_jobs(s, src, FetchResult(jobs=[], complete=True))
            assert st.suspect and st.closed == 0
        assert open_count() == 10

        # A normal turnover still closes the role that disappeared, after two misses.
        for _ in range(2):
            st = upsert_jobs(s, src, FetchResult(jobs=_jobs(9), complete=True))
            assert not st.suspect
        assert open_count() == 9
        s.rollback()
