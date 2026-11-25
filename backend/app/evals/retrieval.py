"""Known-item search eval.

For a stratified sample of jobs we write a query a job seeker might type for that job,
then check where the job (or any duplicate of it) lands. Queries come from an LLM when
one is configured (cached, so reruns are free), otherwise from templates over the
job's structured fields. Compares lexical, dense, hybrid (RRF) and hybrid + reranker.
"""

from __future__ import annotations

import random
import time

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.evals.metrics import mean, mrr_at, ndcg_at, recall_at
from app.llm.router import LLMError, get_llm
from app.models import Job
from app.search.engine import search
from app.search.filters import JobFilters
from app.search.rank import FAMILY_LABEL, LEVEL_LABEL


class Queries(BaseModel):
    queries: list[str]


def template_query(job: Job, rng: random.Random) -> str:
    skills = [s for s in (job.skills or []) if len(s) > 2][:6]
    rng.shuffle(skills)
    parts = []
    if job.seniority in ("intern", "new_grad"):
        parts.append(LEVEL_LABEL[job.seniority].lower())
    parts.append(FAMILY_LABEL.get(job.role_family or "swe", "software").lower())
    parts.append("engineer" if job.role_family not in ("data_science",) else "")
    parts += skills[:2]
    if job.company_name and rng.random() < 0.3:
        parts.append(job.company_name)
    if job.cities and rng.random() < 0.5:
        parts.append(job.cities[0])
    elif job.remote_type == "remote" and rng.random() < 0.5:
        parts.append("remote")
    return " ".join(p for p in parts if p)


def llm_query(job: Job) -> str | None:
    llm = get_llm()
    if not llm.available:
        return None
    prompt = (
        "Write one short search query (4-9 words) a job seeker might type that should find this job. "
        "Describe the work, not the exact title; do not include the company name.\n"
        f"Title: {job.title}\nSkills: {', '.join((job.skills or [])[:10])}\nLocation: {job.location_raw}\n"
        f"Summary: {(job.summary or job.description_text or '')[:600]}\n"
        'Return {"queries": ["..."]}'
    )
    try:
        return llm.structured(
            [{"role": "user", "content": prompt}], Queries, purpose="eval"
        ).queries[0]
    except (LLMError, ValueError, IndexError):
        return None


def sample_jobs(session: Session, n: int, seed: int) -> list[Job]:
    base = select(Job).where(
        Job.status == "open",
        Job.is_tech.is_(True),
        Job.duplicate_of.is_(None),
        Job.embedding.is_not(None),
    )
    jobs = list(
        session.scalars(base.order_by(func.md5(func.concat(Job.id, str(seed)))).limit(n * 3))
    )
    # Stratify by role family so a few huge employers don't dominate.
    by_family: dict[str, list[Job]] = {}
    for j in jobs:
        by_family.setdefault(j.role_family or "swe", []).append(j)
    out: list[Job] = []
    while len(out) < n and any(by_family.values()):
        for fam in list(by_family):
            if by_family[fam]:
                out.append(by_family[fam].pop())
            if len(out) >= n:
                break
    return out


VARIANTS = {
    "lexical": {"mode": "lexical", "use_rerank": False},
    "dense": {"mode": "dense", "use_rerank": False},
    "hybrid_rrf": {"mode": "hybrid", "use_rerank": False},
    "hybrid_rerank": {"mode": "hybrid", "use_rerank": True},
}


def run(session: Session, n: int = 150, seed: int = 7, use_llm: bool = True) -> dict[str, dict]:
    rng = random.Random(seed)
    jobs = sample_jobs(session, n, seed)
    cases = []
    for j in jobs:
        q = (llm_query(j) if use_llm else None) or template_query(j, rng)
        dupes = set(session.scalars(select(Job.id).where(Job.duplicate_of == j.id)))
        cases.append((q, {j.id} | dupes))
    query_source = "llm" if use_llm and get_llm().available else "template"
    results: dict[str, dict] = {}
    for name, cfg in VARIANTS.items():
        r10, r50, mrr, ndcg, lat = [], [], [], [], []
        for q, relevant in cases:
            t = time.perf_counter()
            ranked = [r.job.id for r in search(session, q, JobFilters(), limit=50, **cfg)]
            lat.append((time.perf_counter() - t) * 1000)
            r10.append(recall_at(ranked, relevant, 10))
            r50.append(recall_at(ranked, relevant, 50))
            mrr.append(mrr_at(ranked, relevant, 10))
            ndcg.append(ndcg_at(ranked, {i: 1 for i in relevant}, 10))
        lat.sort()
        results[name] = {
            "recall@10": round(mean(r10), 4),
            "recall@50": round(mean(r50), 4),
            "mrr@10": round(mean(mrr), 4),
            "ndcg@10": round(mean(ndcg), 4),
            "p50_ms": round(lat[len(lat) // 2], 1),
            "p95_ms": round(lat[int(len(lat) * 0.95) - 1], 1),
            "queries": len(cases),
            "query_source": query_source,
        }
    return results
