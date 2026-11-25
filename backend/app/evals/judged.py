"""Judged relevance for the recommendation feed (TREC-style pooling).

1. Personas (``evals/data/personas.yaml``) are split into dev (tuning) and test (reporting).
2. ``pool`` runs many ranking variants per persona and unions their top-k: the pool.
3. Each pooled (persona, job) pair gets a graded judgement 0-3 against a written rubric
   (``evals/data/qrels.jsonl``). Judgements never look at the ranker's scores.
4. Metrics are computed on judged documents only ("condensed" lists) plus bpref, which
   are robust to unjudged documents, and the share of the top-10 that is judged is
   reported so gaps are visible. New variants surface new documents; re-pool and judge
   them before trusting a comparison (iterative pooling).

Rubric (written before judging):
  3  would apply today: right kind of role, right level (or unstated and plausible),
     location workable, and most of the core skills
  2  good fit with one minor gap (adjacent specialisation, a few missing skills,
     level unstated but posting reads senior-ish)
  1  marginal: related, but a clear mismatch (level one step off, different
     specialisation, or asks for notably more experience)
  0  not relevant: wrong kind of role, clearly senior/staff for a student, location
     the persona cannot take, or experience far beyond theirs
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.enrich.embed import embed_query
from app.ingest.text import display_title
from app.search.engine import recommend
from app.search.filters import JobFilters
from app.search.personalize import _expand_families
from app.search.rank import Ranked, UserContext, Weights

DATA = Path(__file__).resolve().parents[2] / "evals" / "data"
PERSONAS = DATA / "personas.yaml"
QRELS = DATA / "qrels.jsonl"


@dataclass
class Persona:
    id: str
    split: str
    groups: list[str]
    text: str
    skills: list[str]
    years: float
    levels: list[str]
    families: list[str]
    cities: list[str]


def load_personas(split: str | None = None) -> list[Persona]:
    rows = yaml.safe_load(PERSONAS.read_text(encoding="utf-8"))
    out = [Persona(**r) for r in rows]
    return [p for p in out if split is None or p.split == split]


_QVEC: dict[str, object] = {}


def context(p: Persona) -> tuple[UserContext, JobFilters]:
    if p.id not in _QVEC:
        _QVEC[p.id] = embed_query(p.text + " Skills: " + ", ".join(p.skills))
    ctx = UserContext(
        skills=set(p.skills),
        years=p.years,
        levels=p.levels,
        families=p.families,
        cities=p.cities,
        qvec=_QVEC[p.id],
        lex_terms=p.skills[:10],
    )
    f = JobFilters(
        seniorities=p.levels,
        role_families=_expand_families(p.families),
        cities=p.cities,
        remote_india=True,
        remote_global=True,
    )
    return ctx, f


def pool_variants(base: Weights) -> dict[str, tuple[Weights, str]]:
    """Deliberately different rankers, so the pool covers what any of them would show."""
    return {
        "dense_only": (
            replace(
                base,
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
            "dense",
        ),
        "lexical_only": (
            replace(
                base,
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
            "lexical",
        ),
        "rrf_only": (
            replace(
                base,
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
            "hybrid",
        ),
        "default": (base, "hybrid"),
        "skills_heavy": (replace(base, semantic=0.15, skills=0.5), "hybrid"),
        "semantic_heavy": (replace(base, semantic=0.6, skills=0.1), "hybrid"),
        "level_heavy": (replace(base, level=0.35, semantic=0.25), "hybrid"),
        "mmr": (replace(base, mmr_lambda=0.7), "hybrid"),
    }


def run_variant(
    session: Session, p: Persona, w: Weights, mode: str = "hybrid", k: int = 20
) -> list[Ranked]:
    ctx, f = context(p)
    return recommend(session, ctx, f, limit=k, weights=w, mode=mode, relax=False)


def load_qrels() -> dict[str, dict[str, int]]:
    q: dict[str, dict[str, int]] = {}
    if QRELS.exists():
        for line in QRELS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                q.setdefault(r["persona"], {})[r["job"]] = int(r["grade"])
    return q


def add_qrels(rows: list[dict]) -> int:
    existing = load_qrels()
    new = [r for r in rows if r["job"] not in existing.get(r["persona"], {})]
    with QRELS.open("a", encoding="utf-8", newline="\n") as fh:
        for r in new:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(new)


def _summary(r: Ranked) -> str:
    j = r.job
    where = ", ".join(j.cities or []) or (
        "Remote" if j.remote_type == "remote" else (j.location_raw or "")[:30]
    )
    if j.remote_type == "remote" and j.cities:
        where += " (remote)"
    countries = ",".join(c for c in (j.countries or []) if not c.startswith("R:"))
    text = re.sub(r"\s+", " ", (j.summary or j.description_text or ""))[:220]
    return (
        f"{display_title(j.title)} | {j.company_name} | {where} [{countries}] | level={j.seniority} "
        f"| family={j.role_family} | min_yoe={j.min_yoe} | skills={', '.join((j.skills or [])[:10])} | {text}"
    )


def pool(
    session: Session,
    personas: list[Persona],
    extra: dict[str, Weights] | None = None,
    depth: int = 10,
) -> dict:
    """Unjudged (persona, job) pairs from the top ``depth`` of every variant."""
    qrels = load_qrels()
    out: dict[str, list[tuple[str, str]]] = {}
    base = Weights()
    variants = pool_variants(base)
    for name, w in (extra or {}).items():
        variants[name] = (w, "hybrid")
    for p in personas:
        seen: dict[str, str] = {}
        for w, mode in variants.values():
            for r in run_variant(session, p, w, mode, k=depth):
                jid = str(r.job.id)
                if jid not in seen and jid not in qrels.get(p.id, {}):
                    seen[jid] = _summary(r)
        out[p.id] = list(seen.items())
    return out
