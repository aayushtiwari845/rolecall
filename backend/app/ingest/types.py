from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class RawJob:
    """A posting as fetched from a source, before enrichment.

    Adapters fill what their source provides; everything optional stays None and is
    inferred later from the text by the enrichment rules.
    """

    source_kind: str
    source_job_id: str
    company_name: str
    title: str
    url: str
    description_text: str = ""
    apply_url: str | None = None
    location_raw: str | None = None
    department: str | None = None
    posted_at: datetime | None = None
    # Structured hints some sources provide directly
    remote_hint: str | None = None  # onsite / hybrid / remote
    employment_hint: str | None = None  # full_time / intern / contract / part_time
    countries_hint: list[str] = field(default_factory=list)
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None  # year / month / hour


@dataclass(slots=True)
class FetchResult:
    jobs: list[RawJob]
    # True when the source returns its complete list of open jobs (ATS boards), so jobs
    # missing from a run can be closed. Aggregators are partial and expire by age instead.
    complete: bool = True
