"""Recruitee careers site API: https://docs.recruitee.com/reference/offers"""

from __future__ import annotations

from app.ingest.http import PoliteClient
from app.ingest.text import clean_text, html_to_text, parse_dt
from app.ingest.types import FetchResult, RawJob

API = "https://{key}.recruitee.com/api/offers/"

_EMPLOYMENT = {"fulltime": "full_time", "parttime": "part_time", "internship": "intern", "contract": "contract"}


def parse(payload: dict, key: str, company_name: str | None) -> list[RawJob]:
    jobs = []
    for o in payload.get("offers", []):
        text = clean_text(
            html_to_text(o.get("description")) + "\n\n" + html_to_text(o.get("requirements"))
        )
        emp = (o.get("employment_type_code") or "").replace("_", "").lower()
        remote = "remote" if o.get("remote") else ("hybrid" if o.get("hybrid") else None)
        salary = o.get("salary") or {}
        jobs.append(
            RawJob(
                source_kind="recruitee",
                source_job_id=f"{key}:{o['id']}",
                company_name=o.get("company_name") or company_name or key,
                title=(o.get("title") or "").strip(),
                url=o.get("careers_url") or f"https://{key}.recruitee.com/o/{o.get('slug')}",
                apply_url=o.get("careers_apply_url"),
                description_text=text,
                location_raw=o.get("location") or None,
                department=o.get("department"),
                posted_at=parse_dt(o.get("published_at") or o.get("created_at")),
                remote_hint=remote,
                employment_hint=next((v for k, v in _EMPLOYMENT.items() if k in emp), None),
                countries_hint=[o["country_code"]] if o.get("country_code") else [],
                salary_min=_num(salary.get("min")),
                salary_max=_num(salary.get("max")),
                salary_currency=salary.get("currency"),
                salary_period=salary.get("period"),
            )
        )
    return jobs


def _num(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


async def fetch(client: PoliteClient, key: str, company_name: str | None = None) -> FetchResult:
    payload = await client.get_json(API.format(key=key))
    return FetchResult(parse(payload, key, company_name), complete=True)
