"""Optional LLM refinement of job fields the rules cannot infer well.

Runs on a daily budget (free tiers), prioritising the jobs users are most likely to see:
new, early-career, India/remote roles. Each call is cached by content, so re-running
costs nothing for unchanged postings.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enrich.skills import canonicalize
from app.llm.router import LLMError, LLMRouter, get_llm
from app.models import Job, LLMCall

log = logging.getLogger(__name__)

Level = Literal["intern", "new_grad", "junior", "mid", "senior", "staff_plus"]
Family = Literal[
    "swe",
    "backend",
    "frontend",
    "fullstack",
    "mobile",
    "ml",
    "ai_llm",
    "data_eng",
    "data_science",
    "infra",
    "security",
    "qa",
    "embedded",
    "other",
]


class JobExtraction(BaseModel):
    summary: str = Field(
        description="One or two plain sentences: what the person in this role will actually do."
    )
    seniority: Level | None = Field(None, description="Experience level the posting targets.")
    role_family: Family | None = None
    min_years_experience: float | None = Field(
        None, description="Minimum years required, null if not stated."
    )
    required_skills: list[str] = Field(
        default_factory=list, description="Concrete technical skills required (max 12)."
    )
    nice_to_have_skills: list[str] = Field(default_factory=list, description="Max 8.")
    open_to_freshers: bool | None = Field(
        None, description="True if students / fresh graduates can apply."
    )


PROMPT = """Extract structured information from this job posting.
Title: {title}
Company: {company}
Location: {location}

Posting:
{text}"""


def extract(llm: LLMRouter, job: Job) -> JobExtraction:
    msg = PROMPT.format(
        title=job.title,
        company=job.company_name,
        location=job.location_raw or "n/a",
        text=(job.description_text or "")[:6000],
    )
    return llm.structured(
        [{"role": "user", "content": msg}], JobExtraction, tier="fast", purpose="enrich"
    )


def apply_extraction(job: Job, ex: JobExtraction) -> None:
    job.summary = ex.summary.strip()[:600] or None
    # Rules are precise when they fire on the title; the LLM fills the gaps.
    if ex.seniority and job.seniority is None:
        job.seniority = ex.seniority
    if (
        ex.seniority in ("intern", "new_grad")
        and ex.open_to_freshers
        and job.seniority in (None, "mid", "junior")
    ):
        job.seniority = ex.seniority
    if ex.role_family and job.role_family in (None, "swe", "other"):
        job.role_family = ex.role_family
    if (
        job.min_yoe is None
        and ex.min_years_experience is not None
        and 0 <= ex.min_years_experience <= 15
    ):
        job.min_yoe = ex.min_years_experience
    extra = [canonicalize(s) for s in ex.required_skills + ex.nice_to_have_skills]
    merged = list(dict.fromkeys([*(job.skills or []), *(s for s in extra if s)]))
    job.skills = merged[:40]
    job.enriched_by = "rules+llm"
    job.embedded_hash = None  # summary/skills feed the embedding text


def budget_left(session: Session) -> int:
    since = datetime.now(UTC) - timedelta(days=1)
    used = (
        session.scalar(
            select(func.count())
            .select_from(LLMCall)
            .where(
                LLMCall.purpose == "enrich",
                LLMCall.created_at >= since,
                LLMCall.cache_hit.is_(False),
            )
        )
        or 0
    )
    return max(0, get_settings().enrich_llm_daily_budget - used)


def enrich_pending(session: Session, limit: int | None = None, llm: LLMRouter | None = None) -> int:
    llm = llm or get_llm()
    if not llm.available:
        log.info("no LLM configured; skipping LLM enrichment")
        return 0
    n = min(limit or 10**9, budget_left(session))
    if n <= 0:
        return 0
    priority = (
        func.coalesce(Job.seniority.in_(["intern", "new_grad", "junior"]), False).desc(),
        or_(Job.countries.any("IN"), Job.remote_type == "remote").desc(),
        Job.first_seen_at.desc(),
    )
    jobs = list(
        session.scalars(
            select(Job)
            .where(
                Job.status == "open",
                Job.is_tech.is_(True),
                Job.enriched_by == "rules",
                Job.duplicate_of.is_(None),
            )
            .order_by(*priority)
            .limit(n)
        )
    )
    done = 0
    for job in jobs:
        try:
            apply_extraction(job, extract(llm, job))
            done += 1
        except LLMError as e:
            log.warning("LLM enrichment stopped: %s", e)
            break
        except Exception:  # noqa: BLE001 - one bad posting shouldn't stop the batch
            log.exception("LLM extraction failed for %s", job.id)
            job.enriched_by = "rules+llm_failed"
        session.commit()
    return done
