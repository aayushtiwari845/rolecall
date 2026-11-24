"""Public remote-job aggregator APIs. Every job links back to the original listing."""

from __future__ import annotations

from app.ingest.http import PoliteClient
from app.ingest.text import html_to_text, parse_dt
from app.ingest.types import FetchResult, RawJob

REMOTIVE = "https://remotive.com/api/remote-jobs"
REMOTIVE_CATEGORIES = ["software-dev", "data", "devops", "qa"]
ARBEITNOW = "https://www.arbeitnow.com/api/job-board-api"
REMOTEOK = "https://remoteok.com/api"


def _emp(value: str | None) -> str | None:
    v = (value or "").lower()
    if "intern" in v:
        return "intern"
    if "contract" in v or "freelance" in v:
        return "contract"
    if "part" in v:
        return "part_time"
    if "full" in v:
        return "full_time"
    return None


def parse_remotive(payload: dict) -> list[RawJob]:
    return [
        RawJob(
            source_kind="remotive",
            source_job_id=str(j["id"]),
            company_name=j.get("company_name") or "Unknown",
            title=(j.get("title") or "").strip(),
            url=j["url"],
            description_text=html_to_text(j.get("description")),
            location_raw=j.get("candidate_required_location") or "Remote",
            department=j.get("category"),
            posted_at=parse_dt(j.get("publication_date")),
            remote_hint="remote",
            employment_hint=_emp(j.get("job_type")),
        )
        for j in payload.get("jobs", [])
    ]


async def fetch_remotive(
    client: PoliteClient, key: str = "", company_name: str | None = None
) -> FetchResult:
    jobs: dict[str, RawJob] = {}
    for cat in [key] if key else REMOTIVE_CATEGORIES:
        payload = await client.get_json(REMOTIVE, params={"category": cat})
        for j in parse_remotive(payload):
            jobs[j.source_job_id] = j
    return FetchResult(list(jobs.values()), complete=False)


def parse_arbeitnow(payload: dict) -> list[RawJob]:
    return [
        RawJob(
            source_kind="arbeitnow",
            source_job_id=j["slug"],
            company_name=j.get("company_name") or "Unknown",
            title=(j.get("title") or "").strip(),
            url=j["url"],
            description_text=html_to_text(j.get("description")),
            location_raw=j.get("location"),
            posted_at=parse_dt(j.get("created_at")),
            remote_hint="remote" if j.get("remote") else None,
            employment_hint=_emp(" ".join(j.get("job_types") or [])),
        )
        for j in payload.get("data", [])
    ]


async def fetch_arbeitnow(
    client: PoliteClient, key: str = "", company_name: str | None = None
) -> FetchResult:
    jobs: list[RawJob] = []
    for page in range(1, 6):
        payload = await client.get_json(ARBEITNOW, params={"page": page})
        batch = parse_arbeitnow(payload)
        jobs.extend(batch)
        if not batch or not (payload.get("links") or {}).get("next"):
            break
    return FetchResult(jobs, complete=False)


def parse_remoteok(payload: list) -> list[RawJob]:
    jobs = []
    for j in payload:
        if not isinstance(j, dict) or "id" not in j or "position" not in j:
            continue  # first element is the API's legal notice
        jobs.append(
            RawJob(
                source_kind="remoteok",
                source_job_id=str(j["id"]),
                company_name=j.get("company") or "Unknown",
                title=(j.get("position") or "").strip(),
                url=j.get("url") or f"https://remoteok.com/remote-jobs/{j['id']}",
                apply_url=j.get("apply_url"),
                description_text=html_to_text(j.get("description")),
                location_raw=j.get("location") or "Remote",
                posted_at=parse_dt(j.get("epoch") or j.get("date")),
                remote_hint="remote",
                salary_min=j.get("salary_min") or None,
                salary_max=j.get("salary_max") or None,
                salary_currency="USD" if j.get("salary_min") else None,
                salary_period="year" if j.get("salary_min") else None,
            )
        )
    return jobs


async def fetch_remoteok(
    client: PoliteClient, key: str = "", company_name: str | None = None
) -> FetchResult:
    payload = await client.get_json(REMOTEOK)
    return FetchResult(parse_remoteok(payload if isinstance(payload, list) else []), complete=False)
