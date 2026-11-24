"""Lever postings API: https://github.com/lever/postings-api"""

from __future__ import annotations

from app.ingest.http import PoliteClient
from app.ingest.text import clean_text, html_to_text, parse_dt
from app.ingest.types import FetchResult, RawJob

API = "https://api.lever.co/v0/postings/{key}"

_WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}
_COMMITMENT = {"intern": "intern", "internship": "intern", "contract": "contract", "part": "part_time"}
_INTERVAL = {"per-year-salary": "year", "per-month-salary": "month", "per-hour-wage": "hour"}


def _employment(commitment: str | None) -> str | None:
    c = (commitment or "").lower()
    for needle, value in _COMMITMENT.items():
        if needle in c:
            return value
    return "full_time" if "full" in c else None


def parse(payload: list, key: str, company_name: str | None) -> list[RawJob]:
    jobs = []
    for p in payload:
        cats = p.get("categories") or {}
        sections = [p.get("descriptionPlain") or html_to_text(p.get("description"))]
        for lst in p.get("lists") or []:
            sections.append(f"{lst.get('text', '')}\n{html_to_text(lst.get('content'))}")
        sections.append(p.get("additionalPlain") or "")
        salary = p.get("salaryRange") or {}
        locations = cats.get("allLocations") or ([cats["location"]] if cats.get("location") else [])
        jobs.append(
            RawJob(
                source_kind="lever",
                source_job_id=f"{key}:{p['id']}",
                company_name=company_name or key,
                title=(p.get("text") or "").strip(),
                url=p.get("hostedUrl") or f"https://jobs.lever.co/{key}/{p['id']}",
                apply_url=p.get("applyUrl"),
                description_text=clean_text("\n\n".join(s for s in sections if s)),
                location_raw="; ".join(locations) or None,
                department=cats.get("team") or cats.get("department"),
                posted_at=parse_dt(p.get("createdAt")),
                remote_hint=_WORKPLACE.get((p.get("workplaceType") or "").lower()),
                employment_hint=_employment(cats.get("commitment")),
                countries_hint=[p["country"]] if p.get("country") else [],
                salary_min=salary.get("min"),
                salary_max=salary.get("max"),
                salary_currency=salary.get("currency"),
                salary_period=_INTERVAL.get(salary.get("interval") or ""),
            )
        )
    return jobs


async def fetch(client: PoliteClient, key: str, company_name: str | None = None) -> FetchResult:
    payload = await client.get_json(API.format(key=key), params={"mode": "json"})
    if not isinstance(payload, list):
        payload = []
    return FetchResult(parse(payload, key, company_name), complete=True)
