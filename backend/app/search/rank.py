"""Second-stage ranking: interpretable features -> weighted score -> diversified list.

Each feature is in [0, 1] and has a plain-language reason attached, so every
recommendation can explain itself ("Matches 6 of your skills", "Asks for 3+ years").

Every tunable number lives in ``Weights`` (the ranking configuration): feature weights,
feature shape parameters, the experience penalty, diversity and retrieval pool sizes.
Offline tuning (``app/evals/tune.py``) searches this space and writes the winning
configuration to ``tuned_config.json``, which ``load_config()`` picks up.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

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
FEATURES = ("semantic", "lexical", "skills", "level", "role", "location", "recency", "affinity")
TUNED_FILE = Path(__file__).with_name("tuned_config.json")


@dataclass
class Weights:
    """The full ranking configuration (name kept for backwards compatibility)."""

    # Feature weights. Lexical match feeds candidate retrieval (RRF) but not the score by
    # default, so a role scores the same wherever it is shown (feed, search, job page).
    semantic: float = 0.33
    lexical: float = 0.0
    skills: float = 0.27
    level: float = 0.15
    role: float = 0.07
    location: float = 0.05
    recency: float = 0.05
    affinity: float = 0.05
    # Feature shapes
    sim_floor: float = 0.5  # cosine at which semantic fit is 0
    sim_span: float = 0.35  # cosine range mapped onto [0, 1]
    skill_saturation: int = 6  # matching this many strong skills = full skill fit
    level_adjacent: float = 0.5  # one level away
    level_two_away: float = 0.15
    level_unknown: float = 0.55  # posting never states a level
    role_adjacent: float = 0.75  # generic SWE / full-stack for a backend or frontend user
    role_other: float = 0.3
    recency_tau_days: float = 21.0  # exp(-age / tau)
    negative_weight: float = 0.7  # pull of disliked roles in the affinity feature
    # Experience penalty
    yoe_penalty: bool = True
    yoe_slack: float = 1.0  # years beyond the user's experience tolerated for free
    yoe_step: float = 0.2  # score multiplier lost per extra year
    yoe_floor: float = 0.3
    # Diversity
    diversify: bool = True
    max_per_company: int = 2
    diversity_window: int = 20
    mmr_lambda: float = 1.0  # 1.0 = off; lower trades relevance for embedding diversity
    # Retrieval
    k_dense: int = 300
    k_lex: int = 150
    rrf_k: int = 60
    w_dense: float = 1.0
    w_lex: float = 1.0
    # Search reranking (cross-encoder over the fused head)
    rerank_head: int = 40
    rerank_blend: float = 0.65  # share of the cross-encoder in the head's relevance
    # Feed fallbacks
    min_results: int = 20  # below this, preferences are relaxed step by step

    @property
    def total(self) -> float:
        return sum(getattr(self, k) for k in FEATURES) or 1.0

    def shares(self) -> dict[str, float]:
        t = self.total
        return {k: round(getattr(self, k) / t, 3) for k in FEATURES if getattr(self, k) > 0}

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Weights:
        names = {f.name for f in fields(cls)}
        base = asdict(cls())
        base.update({k: v for k, v in data.items() if k in names})
        return cls(**base)


@lru_cache(maxsize=1)
def load_config() -> Weights:
    """The tuned configuration when one has been validated, else the defaults."""
    try:
        data = json.loads(TUNED_FILE.read_text(encoding="utf-8"))
        return Weights.from_dict(data["config"])
    except (OSError, ValueError, KeyError, TypeError):
        return Weights()


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
    # Changes whenever the user's resume, feedback or tracker changes. Part of the feed
    # cache key, so every API process sees a change without being told about it.
    state_key: str = ""


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
    weights: dict[str, float] = field(default_factory=dict)  # share of the score per feature


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def level_fit(job_level: str | None, targets: list[str], w: Weights | None = None) -> float:
    w = w or Weights()
    if not targets:
        return 0.7
    if job_level is None:
        return w.level_unknown
    if job_level in targets:
        return 1.0
    idx = LEVELS.index(job_level)
    dist = min(abs(idx - LEVELS.index(t)) for t in targets)
    return {1: w.level_adjacent, 2: w.level_two_away}.get(dist, 0.0)


def role_fit(family: str | None, targets: list[str], w: Weights | None = None) -> float:
    w = w or Weights()
    if not targets:
        return 0.7
    if family in targets:
        return 1.0
    if family == "swe" or (family == "fullstack" and {"backend", "frontend"} & set(targets)):
        return w.role_adjacent
    return w.role_other


def skill_match(
    job_skills: list[str], user_skills: set[str], saturation: int = 6
) -> tuple[float, list[str], list[str]]:
    strong = [s for s in job_skills if s not in WEAK_SKILLS]
    if not strong:
        return 0.5, [s for s in job_skills if s in user_skills], []
    matched = [s for s in strong if s in user_skills]
    missing = [s for s in strong if s not in user_skills]
    # Saturates: matching N of a long wish-list is as good as matching all of a short one.
    denom = max(1, min(len(strong), saturation))
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


def recency(job: Job, now: datetime, tau: float = 21.0) -> tuple[float, int]:
    ts = job.posted_at or job.first_seen_at
    age = max(0.0, (now - ts).total_seconds() / 86400) if ts else 30.0
    return math.exp(-age / max(tau, 0.1)), int(age)


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


def calibrate_similarity(cos: float, floor: float = 0.5, span: float = 0.35) -> float:
    """Map bge-small cosine similarity (profile vs posting, typically 0.5-0.85) to [0, 1]."""
    return max(0.0, min(1.0, (cos - floor) / max(span, 1e-6)))


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
    total_w = w.total
    shares = w.shares()
    out = []
    for i, c in enumerate(cands):
        job = jobs[c.job_id]
        emb = np.asarray(job.embedding, dtype=np.float32) if job.embedding is not None else None
        f: dict[str, float] = {}
        if relevance is not None:
            f["semantic"] = relevance.get(c.job_id, 0.0)
            f["lexical"] = 0.0
        else:
            # Absolute, calibrated similarity (not min-max within a result set), so the
            # same profile and role always get the same semantic score.
            f["semantic"] = (
                calibrate_similarity(_cos(emb, user.qvec), w.sim_floor, w.sim_span)
                if user.qvec is not None
                else sem[i]
            )
            f["lexical"] = lex[i] if c.lex_rank else 0.0
        f["skills"], matched, missing = skill_match(
            job.skills or [], user.skills, w.skill_saturation
        )
        f["level"] = level_fit(job.seniority, user.levels, w)
        f["role"] = role_fit(job.role_family, user.families, w)
        f["location"], loc_reason = location_fit(job, user.cities)
        f["recency"], age = recency(job, now, w.recency_tau_days)
        aff = _cos(emb, user.pos_centroid) - w.negative_weight * _cos(emb, user.neg_centroid)
        aff += user.company_affinity.get(job.company_name, 0.0)
        f["affinity"] = max(0.0, min(1.0, 0.5 + aff))
        raw = sum(getattr(w, k) * f[k] for k in FEATURES) / total_w
        warnings: list[str] = []
        if w.yoe_penalty and job.min_yoe is not None and job.min_yoe > user.years + w.yoe_slack:
            gap = job.min_yoe - user.years - w.yoe_slack
            raw *= max(w.yoe_floor, 1 - w.yoe_step * gap)
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
                weights=shares,
            )
        )
    # Deterministic order: score, then freshness, then id (stable across runs and pages).
    out.sort(
        key=lambda r: (
            -r.score,
            -(r.job.posted_at or r.job.first_seen_at or now).timestamp(),
            str(r.job.id),
        )
    )
    return out


def mmr(items: list[Ranked], lam: float, top: int = 60) -> list[Ranked]:
    """Maximal marginal relevance over the head: trade a little score for roles that
    are less similar (in embedding space) to ones already shown."""
    if lam >= 1.0 or len(items) < 3:
        return items
    head, tail = items[:top], items[top:]
    n = len(head)
    # One similarity matrix and a running "closest already-chosen" vector: O(n^2) numpy
    # instead of O(n^3) Python. Roles without an embedding are similar to nothing.
    dim = next((len(r.job.embedding) for r in head if r.job.embedding is not None), 0)
    mat = np.zeros((n, max(dim, 1)), dtype=np.float32)
    for i, r in enumerate(head):
        if r.job.embedding is not None:
            v = np.asarray(r.job.embedding, dtype=np.float32)
            mat[i] = v / (np.linalg.norm(v) + 1e-9)
    sims = mat @ mat.T
    scores = np.array([r.score for r in head], dtype=np.float64)
    closest = np.zeros(n)
    taken = np.zeros(n, dtype=bool)
    chosen: list[int] = []
    for _ in range(n):
        val = lam * scores - (1 - lam) * (closest if chosen else 0.0)
        val[taken] = -np.inf
        best = int(np.argmax(val))  # first maximum, so ties keep the incoming order
        chosen.append(best)
        taken[best] = True
        closest = np.maximum(closest, sims[best])
    return [head[i] for i in chosen] + tail


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


def finalize(ranked: list[Ranked], w: Weights) -> list[Ranked]:
    """Apply the configured diversity steps to a scored list."""
    out = mmr(ranked, w.mmr_lambda)
    if w.diversify:
        out = diversify(out, w.max_per_company, w.diversity_window)
    return out
