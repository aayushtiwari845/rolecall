"""Greenhouse job board API: https://developers.greenhouse.io/job-board.html"""

from __future__ import annotations

from app.ingest.http import PoliteClient
from app.ingest.text import html_to_text, parse_dt
from app.ingest.types import FetchResult, RawJob

API = "https://boards-api.greenhouse.io/v1/boards/{key}/jobs"


def parse(payload: dict, key: str, company_name: str | None) -> list[RawJob]:
    jobs = []
    for j in payload.get("jobs", []):
        depts = [d.get("name") for d in j.get("departments") or [] if d.get("name")]
        offices = [o.get("name") for o in j.get("offices") or [] if o.get("name")]
        location = (j.get("location") or {}).get("name") or ", ".join(offices) or None
        jobs.append(
            RawJob(
                source_kind="greenhouse",
                source_job_id=f"{key}:{j['id']}",
                company_name=j.get("company_name") or company_name or key,
                title=(j.get("title") or "").strip(),
                url=j.get("absolute_url") or f"https://boards.greenhouse.io/{key}/jobs/{j['id']}",
                description_text=html_to_text(j.get("content"), unescape=True),
                location_raw=location,
                department=", ".join(depts) or None,
                posted_at=parse_dt(j.get("first_published") or j.get("updated_at")),
            )
        )
    return jobs


async def fetch(client: PoliteClient, key: str, company_name: str | None = None) -> FetchResult:
    payload = await client.get_json(API.format(key=key), params={"content": "true"})
    return FetchResult(parse(payload, key, company_name), complete=True)
