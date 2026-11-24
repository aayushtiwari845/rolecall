"""Hacker News "Ask HN: Who is hiring?" threads, through the public Algolia HN API.

Each top-level comment is one company post. By convention the first line is
``Company | Role(s) | Location | REMOTE/ONSITE | ...``; we parse it heuristically and
leave the rest for the enrichment rules.
"""

from __future__ import annotations

import re

from app.ingest.http import PoliteClient
from app.ingest.text import html_to_text, parse_dt
from app.ingest.types import FetchResult, RawJob

SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
ITEM = "https://hn.algolia.com/api/v1/items/{id}"

_ROLE_WORDS = re.compile(
    r"engineer|developer|scientist|swe|sde|intern|programmer|architect|devops|sre|"
    r"analyst|researcher|ml|founding|full[- ]?stack|backend|frontend|data",
    re.I,
)
_LOC_WORDS = re.compile(r"remote|onsite|on-site|hybrid|,|\b[A-Z]{2}\b|city|india|usa|uk|eu", re.I)
_URL = re.compile(r"https?://\S+")


def parse_header(first_line: str) -> tuple[str, str, str | None, str | None]:
    parts = [p.strip() for p in re.split(r"\s+\|\s+|\s+\|\s*|\s*\|\s+", first_line) if p.strip()]
    if not parts:
        return "Unknown", "Software Engineer", None, None
    company = _URL.sub("", parts[0]).strip(" -–(") or "Unknown"
    rest = parts[1:]
    title = next((p for p in rest if _ROLE_WORDS.search(p) and not _URL.search(p)), None)
    locs = [p for p in rest if p is not title and _LOC_WORDS.search(p) and not _URL.search(p)]
    remote = None
    joined = " ".join(rest).lower()
    if "remote" in joined:
        remote = "hybrid" if "hybrid" in joined else "remote"
    elif "onsite" in joined or "on-site" in joined:
        remote = "onsite"
    return (
        company[:200],
        (title or "Software Engineer")[:400],
        "; ".join(locs)[:500] or None,
        remote,
    )


async def latest_thread_id(client: PoliteClient) -> str | None:
    data = await client.get_json(
        SEARCH, params={"tags": "story,author_whoishiring", "hitsPerPage": 10}
    )
    for hit in data.get("hits", []):
        if "who is hiring" in (hit.get("title") or "").lower():
            return str(hit["objectID"])
    return None


def parse_thread(item: dict) -> list[RawJob]:
    jobs = []
    for c in item.get("children") or []:
        raw = c.get("text") or ""
        if not raw or c.get("author") in (None, "whoishiring"):
            continue
        first = raw.split("<p>", 1)[0]
        header = html_to_text(first)
        if "|" not in header:
            continue
        company, title, loc, remote = parse_header(header)
        jobs.append(
            RawJob(
                source_kind="hn",
                source_job_id=str(c["id"]),
                company_name=company,
                title=title,
                url=f"https://news.ycombinator.com/item?id={c['id']}",
                description_text=html_to_text(raw),
                location_raw=loc,
                posted_at=parse_dt(c.get("created_at")),
                remote_hint=remote,
            )
        )
    return jobs


async def fetch(
    client: PoliteClient, key: str = "latest", company_name: str | None = None
) -> FetchResult:
    thread_id = key if key.isdigit() else await latest_thread_id(client)
    if not thread_id:
        return FetchResult([], complete=False)
    item = await client.get_json(ITEM.format(id=thread_id))
    return FetchResult(parse_thread(item), complete=False)
