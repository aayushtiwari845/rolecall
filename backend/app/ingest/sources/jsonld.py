"""Generic career-page crawler.

Many career sites embed schema.org ``JobPosting`` objects as JSON-LD (Google for Jobs
requires it). Given a careers URL we:

1. fetch the page (respecting robots.txt),
2. extract any JobPosting objects on it,
3. follow same-host links that look like job pages (bounded) and extract from those.

``detect_ats`` is also used by company discovery: if a careers page links to a known
ATS board we can use that board's clean API instead of crawling HTML.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from app.ingest.http import FetchError, PoliteClient
from app.ingest.text import html_to_text, parse_dt, sha
from app.ingest.types import FetchResult, RawJob

MAX_JOB_PAGES = 60
_JOB_LINK = re.compile(r"/(jobs?|careers?|positions?|openings?|vacanc(y|ies)|roles?)/[^/?#]+", re.I)

ATS_PATTERNS = [
    (
        "greenhouse",
        re.compile(
            r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)",
            re.I,
        ),
    ),
    ("lever", re.compile(r"jobs\.lever\.co/([\w.-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w.%-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/([\w-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)", re.I)),
    ("recruitee", re.compile(r"([\w-]+)\.recruitee\.com", re.I)),
]
_ATS_IGNORE = {"embed", "api", "v1", "jobs", "www", "careers", "j"}


def detect_ats(html: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for kind, pat in ATS_PATTERNS:
        for m in pat.finditer(html):
            key = m.group(1).strip("/").lower()
            if key and key not in _ATS_IGNORE and (kind, key) not in found:
                found.append((kind, key))
    return found


def _iter_jsonld(tree: HTMLParser):
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text(deep=True) or "")
        except ValueError:
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                if "@graph" in item:
                    stack.append(item["@graph"])
                t = item.get("@type")
                if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                    yield item


def _location(jp: dict) -> tuple[str | None, list[str], str | None]:
    locs = jp.get("jobLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
    names, countries = [], []
    for loc in locs:
        addr = (loc or {}).get("address") or {}
        if isinstance(addr, str):
            names.append(addr)
            continue
        country = addr.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        parts = [addr.get("addressLocality"), addr.get("addressRegion"), country]
        names.append(", ".join(p for p in parts if p))
        if country:
            countries.append(country)
    remote = "remote" if jp.get("jobLocationType") == "TELECOMMUTE" else None
    return "; ".join(n for n in names if n) or None, countries, remote


def _salary(jp: dict):
    bs = jp.get("baseSalary") or {}
    if not isinstance(bs, dict):
        return None, None, None, None
    val = bs.get("value") or {}
    if not isinstance(val, dict):
        val = {"value": val}
    unit = (val.get("unitText") or "").lower()
    period = {"year": "year", "month": "month", "hour": "hour"}.get(unit)
    lo = val.get("minValue") or val.get("value")
    hi = val.get("maxValue") or val.get("value")
    try:
        return float(lo) if lo else None, float(hi) if hi else None, bs.get("currency"), period
    except (TypeError, ValueError):
        return None, None, None, None


def _emp(et) -> str | None:
    et = " ".join(et) if isinstance(et, list) else str(et or "")
    et = et.upper()
    if "INTERN" in et:
        return "intern"
    if "CONTRACT" in et or "TEMPORARY" in et:
        return "contract"
    if "PART" in et:
        return "part_time"
    if "FULL" in et:
        return "full_time"
    return None


def parse_page(html: str, page_url: str, fallback_company: str | None) -> list[RawJob]:
    tree = HTMLParser(html)
    jobs = []
    for jp in _iter_jsonld(tree):
        org = jp.get("hiringOrganization") or {}
        company = (
            (org.get("name") if isinstance(org, dict) else org)
            or fallback_company
            or urlsplit(page_url).netloc
        )
        url = jp.get("url") or page_url
        loc, countries, remote = _location(jp)
        smin, smax, cur, period = _salary(jp)
        ident = jp.get("identifier")
        ident = ident.get("value") if isinstance(ident, dict) else ident
        jobs.append(
            RawJob(
                source_kind="jsonld",
                source_job_id=str(ident or sha(url, jp.get("title"))[:32]),
                company_name=str(company)[:200],
                title=str(jp.get("title") or "").strip(),
                url=urljoin(page_url, url),
                description_text=html_to_text(jp.get("description"), unescape=True),
                location_raw=loc,
                posted_at=parse_dt(jp.get("datePosted")),
                remote_hint=remote,
                employment_hint=_emp(jp.get("employmentType")),
                countries_hint=countries,
                salary_min=smin,
                salary_max=smax,
                salary_currency=cur,
                salary_period=period,
            )
        )
    return [j for j in jobs if j.title]


def job_links(html: str, page_url: str) -> list[str]:
    host = urlsplit(page_url).netloc
    seen: list[str] = []
    for a in HTMLParser(html).css("a[href]"):
        href = urljoin(page_url, a.attributes.get("href") or "").split("#")[0]
        if (
            urlsplit(href).netloc == host
            and _JOB_LINK.search(href)
            and href != page_url
            and href not in seen
        ):
            seen.append(href)
    return seen[:MAX_JOB_PAGES]


async def fetch(client: PoliteClient, key: str, company_name: str | None = None) -> FetchResult:
    """``key`` is the careers page URL."""
    resp = await client.get(key, check_robots=True)
    jobs = {j.source_job_id: j for j in parse_page(resp.text, str(resp.url), company_name)}
    for link in job_links(resp.text, str(resp.url)):
        try:
            page = await client.get(link, check_robots=True)
        except FetchError:
            continue
        for j in parse_page(page.text, str(page.url), company_name):
            jobs.setdefault(j.source_job_id, j)
    # A careers page may paginate or lazy-load, so treat it as partial.
    return FetchResult(list(jobs.values()), complete=False)
