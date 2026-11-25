"""Recommendation quality for realistic personas.

Each ranking variant produces a top-20 per persona. The union of all variants' results
is judged once (pooling, as in TREC) on a 0-3 scale, by an LLM judge when available and
cached, otherwise by a transparent rule judge. Then nDCG@10 / P@10 per variant.
Also reports catalogue coverage and company diversity, which accuracy alone hides.
"""

from __future__ import annotations

from dataclasses import replace

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.public import DEMO_PROFILES
from app.enrich.embed import embed_query
from app.evals.metrics import mean, ndcg_at, precision_at
from app.llm.router import LLMError, get_llm
from app.models import Job
from app.search.engine import recommend
from app.search.filters import JobFilters
from app.search.rank import UserContext, Weights

PERSONAS = {
    **DEMO_PROFILES,
    "frontend_new_grad": {
        "label": "Frontend new grad",
        "text": "Recent graduate, React and TypeScript projects, Next.js, Tailwind, "
        "accessibility, some Node.js. Wants frontend or full-stack roles.",
        "skills": [
            "React",
            "TypeScript",
            "JavaScript",
            "Next.js",
            "HTML/CSS",
            "Tailwind CSS",
            "Node.js",
            "Git",
        ],
        "levels": ["new_grad", "junior"],
        "families": ["frontend", "fullstack", "swe"],
        "cities": ["Bengaluru", "Pune"],
    },
    "infra_junior": {
        "label": "Infra / SRE junior",
        "text": "1 year as a DevOps engineer: Kubernetes, Terraform, AWS, CI/CD, "
        "Prometheus and Grafana, Linux, Python and Go scripting.",
        "skills": [
            "Kubernetes",
            "Terraform",
            "AWS",
            "CI/CD",
            "Observability",
            "Linux",
            "Python",
            "Go",
            "Docker",
        ],
        "levels": ["new_grad", "junior", "mid"],
        "families": ["infra", "backend", "swe"],
        "cities": ["Bengaluru", "Hyderabad"],
    },
}


def persona_context(p: dict) -> tuple[UserContext, JobFilters]:
    ctx = UserContext(
        skills=set(p["skills"]),
        years=0.0 if "intern" in p["levels"] else 1.0,
        levels=p["levels"],
        families=p["families"],
        cities=p["cities"],
        qvec=embed_query(p["text"]),
        lex_terms=p["skills"][:10],
    )
    f = JobFilters(
        seniorities=p["levels"],
        role_families=p["families"],
        cities=p["cities"],
        remote_india=True,
        remote_global=True,
    )
    return ctx, f


def variants() -> dict[str, dict]:
    full = Weights()
    return {
        "dense_only": {
            "mode": "dense",
            "weights": Weights(
                semantic=1,
                lexical=0,
                skills=0,
                level=0,
                role=0,
                location=0,
                recency=0,
                affinity=0,
                yoe_penalty=False,
                diversify=False,
            ),
        },
        "lexical_only": {
            "mode": "lexical",
            "weights": Weights(
                semantic=0,
                lexical=1,
                skills=0,
                level=0,
                role=0,
                location=0,
                recency=0,
                affinity=0,
                yoe_penalty=False,
                diversify=False,
            ),
        },
        "hybrid_rrf_only": {
            "mode": "hybrid",
            "weights": Weights(
                semantic=0.6,
                lexical=0.4,
                skills=0,
                level=0,
                role=0,
                location=0,
                recency=0,
                affinity=0,
                yoe_penalty=False,
                diversify=False,
            ),
        },
        "ranker_no_yoe_penalty": {"mode": "hybrid", "weights": replace(full, yoe_penalty=False)},
        "ranker_no_diversity": {"mode": "hybrid", "weights": replace(full, diversify=False)},
        "full_ranker": {"mode": "hybrid", "weights": full},
    }


class Judgement(BaseModel):
    score: int = Field(ge=0, le=3, description="0 irrelevant, 1 weak, 2 good, 3 excellent fit")
    reason: str


def rule_judge(p: dict, job: Job) -> int:
    """Transparent fallback judge (independent of the ranker's weights)."""
    score = 0
    if job.role_family in p["families"]:
        score += 1
    if job.seniority in p["levels"]:
        score += 1
    if job.min_yoe is not None and job.min_yoe > (0 if "intern" in p["levels"] else 2) + 1:
        score -= 1
    overlap = len(set(job.skills or []) & set(p["skills"]))
    score += 1 if overlap >= 3 else 0
    return max(0, min(3, score))


def llm_judge(p: dict, job: Job) -> int | None:
    llm = get_llm()
    if not llm.available:
        return None
    prompt = (
        f"Candidate: {p['text']} Target levels: {', '.join(p['levels'])}. Preferred locations: "
        f"{', '.join(p['cities'])} or remote.\n\nJob: {job.title} at {job.company_name} ({job.location_raw}). "
        f"{(job.description_text or '')[:1500]}\n\nHow good a fit is this job for the candidate? "
        "Consider role, level / years asked, skills and location."
    )
    try:
        return llm.structured(
            [{"role": "user", "content": prompt}], Judgement, purpose="eval_judge"
        ).score
    except (LLMError, ValueError):
        return None


def run(session: Session, k: int = 10, use_llm: bool = True) -> dict[str, dict]:
    runs: dict[str, dict[str, list]] = {}
    for vname, cfg in variants().items():
        runs[vname] = {}
        for pid, p in PERSONAS.items():
            ctx, f = persona_context(p)
            items = recommend(session, ctx, f, limit=20, weights=cfg["weights"], mode=cfg["mode"])
            runs[vname][pid] = [r.job for r in items]

    judge_source = "llm" if use_llm and get_llm().available else "rules"
    labels: dict[str, dict] = {pid: {} for pid in PERSONAS}
    for pid, p in PERSONAS.items():
        pool = {j.id: j for v in runs.values() for j in v[pid][:k]}
        for jid, job in pool.items():
            s = llm_judge(p, job) if judge_source == "llm" else None
            labels[pid][jid] = s if s is not None else rule_judge(p, job)

    total_open = session.query(Job).filter(Job.status == "open", Job.is_tech.is_(True)).count() or 1
    out = {}
    for vname, per in runs.items():
        ndcg, prec, uniq_companies, all_ids = [], [], [], set()
        for pid, jobs in per.items():
            ids = [j.id for j in jobs]
            ndcg.append(ndcg_at(ids, labels[pid], k))
            prec.append(precision_at(ids, labels[pid], k))
            uniq_companies.append(len({j.company_name for j in jobs[:k]}) / max(1, len(jobs[:k])))
            all_ids |= set(ids)
        out[vname] = {
            f"ndcg@{k}": round(mean(ndcg), 4),
            f"p@{k}": round(mean(prec), 4),
            "company_diversity": round(mean(uniq_companies), 3),
            "coverage": round(len(all_ids) / total_open, 4),
            "personas": len(PERSONAS),
            "judge": judge_source,
        }
    return out
