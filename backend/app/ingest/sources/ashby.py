"""Ashby public job board API: https://developers.ashbyhq.com/docs/public-job-posting-api"""

from __future__ import annotations

from app.ingest.http import PoliteClient
from app.ingest.text import html_to_text, parse_dt
from app.ingest.types import FetchResult, RawJob

API = "https://api.ashbyhq.com/posting-api/job-board/{key}"

_EMPLOYMENT = {
    "FullTime": "full_time",
    "Intern": "intern",
    "Contract": "contract",
    "PartTime": "part_time",
}
_WORKPLACE = {"Remote": "remote", "Hybrid": "hybrid", "OnSite": "onsite"}
_INTERVAL = {"1 YEAR": "year", "1 MONTH": "month", "1 HOUR": "hour"}


def _salary(comp: dict | None) -> tuple[float | None, float | None, str | None, str | None]:
    for c in (comp or {}).get("summaryComponents") or []:
        if c.get("compensationType") == "Salary":
            return (
                c.get("minValue"),
                c.get("maxValue"),
                c.get("currencyCode"),
                _INTERVAL.get(c.get("interval") or ""),
            )
    return None, None, None, None


def parse(payload: dict, key: str, company_name: str | None) -> list[RawJob]:
    jobs = []
    for j in payload.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locations = [j.get("location")] + [
            s.get("location") for s in j.get("secondaryLocations") or []
        ]
        country = (((j.get("address") or {}).get("postalAddress")) or {}).get("addressCountry")
        smin, smax, cur, period = _salary(j.get("compensation"))
        remote = _WORKPLACE.get(j.get("workplaceType") or "")
        if remote is None and j.get("isRemote"):
            remote = "remote"
        jobs.append(
            RawJob(
                source_kind="ashby",
                source_job_id=f"{key}:{j['id']}",
                company_name=company_name or key,
                title=(j.get("title") or "").strip(),
                url=j.get("jobUrl") or f"https://jobs.ashbyhq.com/{key}/{j['id']}",
                apply_url=j.get("applyUrl"),
                description_text=j.get("descriptionPlain")
                or html_to_text(j.get("descriptionHtml")),
                location_raw="; ".join(loc for loc in locations if loc) or None,
                department=j.get("department") or j.get("team"),
                posted_at=parse_dt(j.get("publishedAt")),
                remote_hint=remote,
                employment_hint=_EMPLOYMENT.get(j.get("employmentType") or ""),
                countries_hint=[country] if country else [],
                salary_min=smin,
                salary_max=smax,
                salary_currency=cur,
                salary_period=period,
            )
        )
    return jobs


async def fetch(client: PoliteClient, key: str, company_name: str | None = None) -> FetchResult:
    payload = await client.get_json(API.format(key=key), params={"includeCompensation": "true"})
    return FetchResult(parse(payload, key, company_name), complete=True)
