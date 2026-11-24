"""Workday career sites (used by most large enterprises).

Workday career pages are backed by a JSON endpoint the page itself calls:
``POST https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs``.
Key format: ``{tenant}.{wd}/{site}``, e.g. ``nvidia.wd5/NVIDIAExternalCareerSite``.

Workday boards are huge, so we search for tech keywords only, cap the number of
postings per run and fetch details only for titles that look like tech roles.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta

from app.enrich.rules import looks_tech_title
from app.ingest.http import FetchError, PoliteClient
from app.ingest.text import html_to_text
from app.ingest.types import FetchResult, RawJob

SEARCH_TERMS = ["software engineer", "developer", "data", "machine learning", "intern"]
PAGE = 20
MAX_PER_TERM = 100


def _base(key: str) -> tuple[str, str, str]:
    host_part, site = key.split("/", 1)
    tenant = host_part.split(".")[0]
    return f"https://{host_part}.myworkdayjobs.com", tenant, site


def _posted(text: str | None) -> datetime | None:
    if not text:
        return None
    now = datetime.now(UTC)
    t = text.lower()
    if "today" in t:
        return now
    if "yesterday" in t:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*days?", t)
    return now - timedelta(days=int(m.group(1))) if m else None


async def fetch(client: PoliteClient, key: str, company_name: str | None = None) -> FetchResult:
    base, tenant, site = _base(key)
    api = f"{base}/wday/cxs/{tenant}/{site}"
    postings: dict[str, dict] = {}
    for term in SEARCH_TERMS:
        offset = 0
        while offset < MAX_PER_TERM:
            data = await client.post_json(  # Workday search is POST-only
                f"{api}/jobs",
                {"appliedFacets": {}, "limit": PAGE, "offset": offset, "searchText": term},
                headers={"Accept": "application/json"},
            )
            batch = data.get("jobPostings") or []
            for p in batch:
                if p.get("externalPath"):
                    postings.setdefault(p["externalPath"], p)
            offset += PAGE
            if len(batch) < PAGE or offset >= (data.get("total") or 0):
                break

    async def detail(path: str, p: dict) -> RawJob | None:
        title = p.get("title") or ""
        if not looks_tech_title(title):
            return None
        info: dict = {}
        try:
            info = (await client.get_json(f"{api}{path}")).get("jobPostingInfo") or {}
        except FetchError:
            pass
        loc = info.get("location") or p.get("locationsText")
        extra = info.get("additionalLocations") or []
        time_type = (info.get("timeType") or "").lower()
        return RawJob(
            source_kind="workday",
            source_job_id=f"{tenant}:{info.get('jobReqId') or path.rsplit('_', 1)[-1]}",
            company_name=company_name or tenant.title(),
            title=title.strip(),
            url=info.get("externalUrl") or f"{base}/{site}{path}",
            description_text=html_to_text(info.get("jobDescription")),
            location_raw="; ".join([loc] + extra if loc else extra) or None,
            posted_at=_posted(p.get("postedOn")),
            employment_hint="part_time" if "part" in time_type else None,
            remote_hint="remote" if "remote" in (info.get("remoteType") or "").lower() else None,
        )

    jobs = await asyncio.gather(*(detail(path, p) for path, p in postings.items()))
    return FetchResult([j for j in jobs if j], complete=False)
