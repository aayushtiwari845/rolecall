"""SmartRecruiters public postings API.

The list endpoint has no descriptions, so details are fetched only for postings whose
title already looks like a tech role (keeps request volume small).
"""

from __future__ import annotations

import asyncio

from app.enrich.rules import looks_tech_title
from app.ingest.http import FetchError, PoliteClient
from app.ingest.text import html_to_text, parse_dt
from app.ingest.types import FetchResult, RawJob

LIST = "https://api.smartrecruiters.com/v1/companies/{key}/postings"
DETAIL = "https://api.smartrecruiters.com/v1/companies/{key}/postings/{id}"
MAX_PAGES = 20

_EMPLOYMENT = {
    "full-time": "full_time",
    "part-time": "part_time",
    "contract": "contract",
    "intern": "intern",
}


def _employment(label: str | None) -> str | None:
    lab = (label or "").lower()
    for needle, value in _EMPLOYMENT.items():
        if needle in lab:
            return value
    return None


def parse_posting(p: dict, detail: dict | None, key: str, company_name: str | None) -> RawJob:
    loc = p.get("location") or {}
    loc_str = loc.get("fullLocation") or ", ".join(
        x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x
    )
    text = ""
    if detail:
        sections = ((detail.get("jobAd") or {}).get("sections")) or {}
        parts = []
        for name in ("jobDescription", "qualifications", "additionalInformation"):
            sec = sections.get(name) or {}
            if sec.get("text"):
                parts.append(f"{sec.get('title', '')}\n{html_to_text(sec['text'])}")
        text = "\n\n".join(parts)
    exp = (p.get("experienceLevel") or {}).get("label") or ""
    if exp:
        text = f"Experience level: {exp}\n\n{text}"
    return RawJob(
        source_kind="smartrecruiters",
        source_job_id=f"{key}:{p['id']}",
        company_name=(p.get("company") or {}).get("name") or company_name or key,
        title=(p.get("name") or "").strip(),
        url=(detail or {}).get("postingUrl") or f"https://jobs.smartrecruiters.com/{key}/{p['id']}",
        apply_url=(detail or {}).get("applyUrl"),
        description_text=text,
        location_raw=loc_str or None,
        department=(p.get("department") or {}).get("label"),
        posted_at=parse_dt(p.get("releasedDate")),
        remote_hint="remote" if loc.get("remote") else None,
        employment_hint=_employment((p.get("typeOfEmployment") or {}).get("label")),
        countries_hint=[loc["country"].upper()] if loc.get("country") else [],
    )


async def fetch(client: PoliteClient, key: str, company_name: str | None = None) -> FetchResult:
    postings: list[dict] = []
    offset = 0
    for _ in range(MAX_PAGES):
        page = await client.get_json(LIST.format(key=key), params={"limit": 100, "offset": offset})
        content = page.get("content") or []
        postings.extend(content)
        offset += len(content)
        if not content or offset >= page.get("totalFound", 0):
            break

    async def detail(p: dict) -> RawJob:
        d = None
        if looks_tech_title(p.get("name") or ""):
            try:
                d = await client.get_json(DETAIL.format(key=key, id=p["id"]))
            except FetchError:
                d = None
        return parse_posting(p, d, key, company_name)

    jobs = await asyncio.gather(*(detail(p) for p in postings))
    return FetchResult(list(jobs), complete=True)
