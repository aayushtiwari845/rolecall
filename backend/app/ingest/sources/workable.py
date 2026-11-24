"""Workable public widget API (used by company career pages)."""

from __future__ import annotations

from app.ingest.http import PoliteClient
from app.ingest.text import html_to_text, parse_dt
from app.ingest.types import FetchResult, RawJob

API = "https://apply.workable.com/api/v1/widget/accounts/{key}"

_EMPLOYMENT = {
    "full-time": "full_time",
    "part-time": "part_time",
    "contract": "contract",
    "internship": "intern",
    "temporary": "contract",
}


def parse(payload: dict, key: str, company_name: str | None) -> list[RawJob]:
    jobs = []
    name = payload.get("name") or company_name or key
    for j in payload.get("jobs", []):
        locs = j.get("locations") or [
            {"city": j.get("city"), "region": j.get("state"), "country": j.get("country")}
        ]
        loc_strs = [
            ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x)
            for loc in locs
        ]
        countries = [loc.get("country") for loc in locs if loc.get("country")]
        code = j.get("shortcode") or j.get("code") or j.get("id")
        jobs.append(
            RawJob(
                source_kind="workable",
                source_job_id=f"{key}:{code}",
                company_name=name,
                title=(j.get("title") or "").strip(),
                url=j.get("url")
                or j.get("shortlink")
                or f"https://apply.workable.com/{key}/j/{code}/",
                apply_url=j.get("application_url"),
                description_text=html_to_text(j.get("description")),
                location_raw="; ".join(s for s in loc_strs if s) or None,
                department=j.get("department"),
                posted_at=parse_dt(j.get("published_on") or j.get("created_at")),
                remote_hint="remote" if j.get("telecommuting") else None,
                employment_hint=_EMPLOYMENT.get((j.get("employment_type") or "").lower()),
                countries_hint=countries,
            )
        )
    return jobs


async def fetch(client: PoliteClient, key: str, company_name: str | None = None) -> FetchResult:
    payload = await client.get_json(API.format(key=key), params={"details": "true"})
    return FetchResult(parse(payload, key, company_name), complete=True)
