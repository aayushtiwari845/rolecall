"""Second-stage ranking: interpretable features -> weighted score -> diversified list.

Each feature is in [0, 1] and has a plain-language reason attached, so every
recommendation can explain itself ("Matches 6 of your skills", "Asks for 3+ years").
Weights are a dataclass so offline evals can compare variants.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np

from app.enrich.skills import WEAK_SKILLS
from app.models import Job
from app.search.retrieval import Candidate

LEVELS = ["intern", "new_grad", "junior", "mid", "senior", "staff_plus"]
LEVEL_LABEL = {
    "intern": "Internship",
    "new_grad": "New grad",
    "junior": "Junior",
    "mid": "Mid-level",
    "senior": "Senior",
    "staff_plus": "Staff+",
}
FAMILY_LABEL = {
    "swe": "Software",
    "backend": "Backend",
    "frontend": "Frontend",
    "fullstack": "Full-stack",
    "mobile": "Mobile",
    "ml": "ML",
    "ai_llm": "AI / LLM",
    "data_eng": "Data engineering",
    "data_science": "Data science",
    "infra": "Infra / DevOps",
    "security": "Security",
    "qa": "QA",
    "embedded": "Embedded",
    "other": "Other",
}


@dataclass
class Weights:
    semantic: float = 0.30
    lexical: float = 0.08
    skills: float = 0.25
    level: float = 0.15
    role: float = 0.07
    location: float = 0.05
    recency: float = 0.05
    affinity: float = 0.05
    yoe_penalty: bool = True
    diversify: bool = True
    max_per_company: int = 2


@dataclass
class UserContext:
    skills: set[str] = field(default_factory=set)
    years: float = 0.0
    levels: list[str] = field(default_factory=list)
    families: list[str] = field(default_factory=list)
    cities: list[str] = field(default_factory=list)
    qvec: np.ndarray | None = None
    lex_terms: list[str] = field(default_factory=list)
    pos_centroid: np.ndarray | None = None
    neg_centroid: np.ndarray | None = None
    company_affinity: dict[str, float] = field(default_factory=dict)
    hidden_job_ids: list[uuid.UUID] = field(default_factory=list)
    saved_job_ids: set[uuid.UUID] = field(default_factory=set)


@dataclass
class Ranked:
    job: Job
    score: float
    match: int
    features: dict[str, float]
    reasons: list[str]
    warnings: list[str]
    matched_skills: list[str]
    missing_skills: list[str]


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def level_fit(job_level: str | None, targets: list[str]) -> float:
    if not targets:
        return 0.7
    if job_level is None:
        return 0.55
    if job_level in targets:
        return 1.0
    idx = LEVELS.index(job_level)
    dist = min(abs(idx - LEVELS.index(t)) for t in targets)
    return {1: 0.5, 2: 0.15}.get(dist, 0.0)


def role_fit(family: str | None, targets: list[str]) -> float:
    if not targets:
        return 0.7
    if family in targets:
        return 1.0
    if family == "swe" or (family == "fullstack" and {"backend", "frontend"} & set(targets)):
        return 0.75
    return 0.3


def skill_match(job_skills: list[str], user_skills: set[str]) -> tuple[float, list[str], list[str]]:
    strong = [s for s in job_skills if s not in WEAK_SKILLS]
    if not strong:
        return 0.5, [s for s in job_skills if s in user_skills], []
    matched = [s for s in strong if s in user_skills]
    missing = [s for s in strong if s not in user_skills]
    # Saturates: matching 6 of a long wish-list is as good as matching all of a short one.
    denom = min(len(strong), 6)
    return min(1.0, len(matched) / denom), matched, missing


def location_fit(job: Job, cities: list[str]) -> tuple[float, str | None]:
    if cities and set(job.cities or []) & set(cities):
        city = next(c for c in job.cities if c in cities)
        return 1.0, f"In {city}" + (" (hybrid)" if job.remote_type == "hybrid" else "")
    if job.remote_type == "remote":
        if "IN" in (job.countries or []):
            return 0.9, "Remote, open to India"
        if "WW" in (job.countries or []):
            return 0.85, "Remote, worldwide"
        return 0.7, "Remote"
    return 0.5, None


def recency(job: Job, now: datetime) -> tuple[float, int]:
    ts = job.posted_at or job.first_seen_at
    age = max(0.0, (now - ts).total_seconds() / 86400) if ts else 30.0
    return math.exp(-age / 21), int(age)


def _cos(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None or b is None:
        return 0.0
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def _age_text(days: int) -> str:
    if days <= 0:
        return "Posted today"
    if days == 1:
        return "Posted yesterday"
    if days < 14:
        return f"Posted {days} days ago"
    if days < 60:
        return f"Posted {days // 7} weeks ago"
    return "Posted a while ago"


def score_candidates(
    cands: list[Candidate],
    jobs: dict[uuid.UUID, Job],
    user: UserContext,
    w: Weights,
    relevance: dict[uuid.UUID, float] | None = None,
) -> list[Ranked]:
    """Score candidates. ``relevance`` (search) replaces semantic+lexical when given."""
    now = datetime.now(UTC)
    cands = [c for c in cands if c.job_id in jobs]
    sem = _minmax([c.dense_sim for c in cands])
    lex = _minmax([c.lex_score for c in cands])
    total_w = (
        w.semantic + w.lexical + w.skills + w.level + w.role + w.location + w.recency + w.affinity
    ) or 1.0
    out = []
    for i, c in enumerate(cands):
        job = jobs[c.job_id]
        f: dict[str, float] = {}
        if relevance is not None:
            f["semantic"] = relevance.get(c.job_id, 0.0)
            f["lexical"] = 0.0
        else:
            f["semantic"] = sem[i] if c.dense_rank else 0.0
            f["lexical"] = lex[i] if c.lex_rank else 0.0
        f["skills"], matched, missing = skill_match(job.skills or [], user.skills)
        f["level"] = level_fit(job.seniority, user.levels)
        f["role"] = role_fit(job.role_family, user.families)
        f["location"], loc_reason = location_fit(job, user.cities)
        f["recency"], age = recency(job, now)
        emb = np.asarray(job.embedding, dtype=np.float32) if job.embedding is not None else None
        aff = _cos(emb, user.pos_centroid) - 0.7 * _cos(emb, user.neg_centroid)
        aff += user.company_affinity.get(job.company_name, 0.0)
        f["affinity"] = max(0.0, min(1.0, 0.5 + aff))
        raw = (
            w.semantic * f["semantic"]
            + w.lexical * f["lexical"]
            + w.skills * f["skills"]
            + w.level * f["level"]
            + w.role * f["role"]
            + w.location * f["location"]
            + w.recency * f["recency"]
            + w.affinity * f["affinity"]
        ) / total_w
        warnings: list[str] = []
        if w.yoe_penalty and job.min_yoe is not None and job.min_yoe > user.years + 1:
            gap = job.min_yoe - user.years - 1
            raw *= max(0.3, 1 - 0.2 * gap)
            warnings.append(f"Asks for {job.min_yoe:g}+ years of experience")
        if f["level"] < 0.5 and job.seniority:
            warnings.append(f"{LEVEL_LABEL.get(job.seniority, job.seniority)} role")

        reasons: list[str] = []
        if matched:
            shown = ", ".join(matched[:4])
            reasons.append(
                f"Matches {len(matched)} of your skills: {shown}"
                if len(matched) > 1
                else f"Uses {shown}"
            )
        if f["level"] >= 1.0 and job.seniority:
            reasons.append(f"Right level: {LEVEL_LABEL[job.seniority].lower()}")
        if f["role"] >= 1.0 and job.role_family:
            reasons.append(
                f"{FAMILY_LABEL.get(job.role_family, job.role_family)} role, as you wanted"
            )
        if loc_reason:
            reasons.append(loc_reason)
        if age <= 7:
            reasons.append(_age_text(age))
        if user.pos_centroid is not None and _cos(emb, user.pos_centroid) > 0.8:
            reasons.append("Similar to jobs you saved")
        out.append(
            Ranked(
                job=job,
                score=raw,
                match=int(round(100 * min(1.0, raw))),
                features=f,
                reasons=reasons,
                warnings=warnings,
                matched_skills=matched,
                missing_skills=missing[:5],
            )
        )
    out.sort(key=lambda r: r.score, reverse=True)
    return out


def diversify(items: list[Ranked], max_per_company: int = 2, window: int = 20) -> list[Ranked]:
    """Cap any one company to ``max_per_company`` slots in each window of results."""
    result: list[Ranked] = []
    deferred: list[Ranked] = []
    counts: dict[str, int] = {}
    for r in items:
        block = len(result) // window
        key = f"{block}:{r.job.company_name}"
        if counts.get(key, 0) < max_per_company:
            counts[key] = counts.get(key, 0) + 1
            result.append(r)
        else:
            deferred.append(r)
    return result + deferred
