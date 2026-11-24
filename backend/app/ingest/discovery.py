"""Company discovery: find which ATS boards a company uses.

For each candidate company we try likely board slugs against every supported ATS's
public API and keep the ones that respond with at least one open job. Results are
written to ``seeds/companies.yaml`` and loaded into the database by ``rolecall seed``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.ingest.http import FetchError, PoliteClient
from app.ingest.sources.jsonld import detect_ats

log = logging.getLogger(__name__)

SEEDS_DIR = Path(__file__).resolve().parents[2] / "seeds"


@dataclass
class Candidate:
    name: str
    slugs: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    careers_url: str | None = None


def load_candidates(path: Path | None = None) -> list[Candidate]:
    """Parse ``candidates.txt``: ``Name | slug1,slug2 | tag1,tag2 | careers_url``."""
    path = path or SEEDS_DIR / "candidates.txt"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")] + ["", "", ""]
        name, slugs, tags, url = parts[:4]
        out.append(
            Candidate(
                name=name,
                slugs=[s for s in slugs.split(",") if s.strip()],
                tags=[t for t in tags.split(",") if t.strip()],
                careers_url=url or None,
            )
        )
    return out


def slug_guesses(c: Candidate) -> list[str]:
    if c.slugs:
        return c.slugs
    base = re.sub(r"[^\w\s.-]", "", c.name.lower()).strip()
    words = re.split(r"[\s.]+", base)
    guesses = ["".join(words), "-".join(words)]
    if words[-1] in {"ai", "labs", "technologies", "inc", "hq", "app", "io"} and len(words) > 1:
        guesses.append("".join(words[:-1]))
    return list(dict.fromkeys(g for g in guesses if g))


async def _probe(client: PoliteClient, kind: str, slug: str) -> int:
    """Return the number of open jobs on this board, or 0 if it does not exist."""
    try:
        if kind == "greenhouse":
            data = await client.get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
            return len(data.get("jobs", []))
        if kind == "lever":
            data = await client.get_json(
                f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}
            )
            return len(data) if isinstance(data, list) else 0
        if kind == "ashby":
            data = await client.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
            return len(data.get("jobs", []))
        if kind == "workable":
            data = await client.get_json(
                f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
            )
            return len(data.get("jobs", []))
        if kind == "smartrecruiters":
            data = await client.get_json(
                f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", params={"limit": 1}
            )
            return int(data.get("totalFound", 0))
        if kind == "recruitee":
            data = await client.get_json(f"https://{slug}.recruitee.com/api/offers/")
            return len(data.get("offers", []))
    except (FetchError, ValueError, AttributeError):
        return 0
    return 0


PROBE_KINDS = ["greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee"]


async def discover_one(client: PoliteClient, c: Candidate) -> dict:
    found: list[dict] = []
    if c.careers_url:
        try:
            resp = await client.get(c.careers_url, check_robots=True)
            for kind, key in detect_ats(resp.text):
                n = await _probe(client, kind, key)
                if n:
                    found.append({"kind": kind, "key": key, "jobs": n})
        except FetchError:
            pass
        if not found:
            found.append({"kind": "jsonld", "key": c.careers_url, "jobs": None})
    if not any(f["kind"] != "jsonld" for f in found):
        for slug in slug_guesses(c):
            results = await asyncio.gather(*(_probe(client, k, slug) for k in PROBE_KINDS))
            hits = [
                {"kind": k, "key": slug, "jobs": n}
                for k, n in zip(PROBE_KINDS, results, strict=True)
                if n
            ]
            if hits:
                found = [f for f in found if f["kind"] != "jsonld"] + hits
                break
    return {"name": c.name, "tags": c.tags, "sources": found}


async def discover(candidates: list[Candidate], concurrency: int = 12) -> list[dict]:
    client = PoliteClient(concurrency=concurrency, per_host_delay=0.2, max_retries=1)
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def run(c: Candidate) -> dict:
        nonlocal done
        async with sem:
            res = await discover_one(client, c)
        done += 1
        if done % 25 == 0:
            log.info("discovery progress: %d/%d", done, len(candidates))
        return res

    try:
        return await asyncio.gather(*(run(c) for c in candidates))
    finally:
        await client.aclose()


def write_seeds(results: list[dict], path: Path | None = None) -> Path:
    path = path or SEEDS_DIR / "companies.yaml"
    found = [r for r in results if r["sources"]]
    found.sort(key=lambda r: r["name"].lower())
    header = (
        "# Generated by `rolecall discover` from candidates.txt. Safe to edit by hand.\n"
        f"# {len(found)} companies with at least one live board.\n"
    )
    path.write_text(
        header + yaml.safe_dump(found, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return path


def load_seeds(path: Path | None = None) -> list[dict]:
    path = path or SEEDS_DIR / "companies.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []
