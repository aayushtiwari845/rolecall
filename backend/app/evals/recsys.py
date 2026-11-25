"""Rigorous offline evaluation of the recommendation feed against judged relevance.

For a ranking configuration it reports, per persona and aggregated with 95% bootstrap
confidence intervals:

- accuracy: condensed nDCG@5/10/20, P@10, MAP, MRR, bpref, Success@5 (a grade-3 role in
  the top 5), and judged@10 (how much of the top 10 has been judged)
- beyond accuracy: intra-list diversity (embedding), distinct companies in the top 10,
  company exposure Gini across personas, median age of the top 10, catalogue coverage
- constraint violations in the top 10: a level the persona excluded, experience asked
  more than two years beyond the persona's, a location the persona cannot take
- stability: rank-biased overlap between the feed and the feed for the same persona
  with one skill removed (small profile edits should not reshuffle everything)
- latency of the full recommend() call
- every metric broken down by persona group (intern / new grad / junior / experienced,
  role area, sparse profile, remote-only)

Candidates are cached per persona, so evaluating a new scoring configuration costs a
few milliseconds and hyperparameter search can run hundreds of trials.
"""

from __future__ import annotations

import random
import statistics
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import numpy as np
from sqlalchemy.orm import Session

from app.evals import metrics as M
from app.evals.judged import Persona, context, load_personas, load_qrels
from app.models import Job
from app.search.engine import _load_jobs, _retrieve
from app.search.rank import Ranked, UserContext, Weights, finalize, score_candidates

K = 10
EARLY = {"intern", "new_grad", "junior"}


@dataclass
class CachedPersona:
    persona: Persona
    ctx: UserContext
    cands: list
    jobs: dict
    perturbed_ctx: UserContext


@dataclass
class EvalResult:
    config: dict
    per_persona: dict[str, dict[str, float]]
    summary: dict[str, dict[str, float]]  # metric -> {mean, lo, hi}
    segments: dict[str, dict[str, float]] = field(default_factory=dict)
    lists: dict[str, list[str]] = field(default_factory=dict)

    def mean(self, metric: str) -> float:
        return self.summary[metric]["mean"]


class Evaluator:
    """Caches retrieval per persona; scores and evaluates configurations quickly."""

    def __init__(
        self,
        session: Session,
        personas: list[Persona] | None = None,
        retrieval: Weights | None = None,
    ):
        self.session = session
        self.personas = personas if personas is not None else load_personas()
        self.qrels = load_qrels()
        self.retrieval = retrieval or Weights()
        self._cache: dict[str, CachedPersona] = {}
        self.catalogue = None

    def _prepare(self, p: Persona) -> CachedPersona:
        if p.id in self._cache:
            return self._cache[p.id]
        ctx, f = context(p)
        cands = _retrieve(self.session, ctx, f, self.retrieval, "hybrid")
        jobs = _load_jobs(self.session, [c.job_id for c in cands])
        rng = random.Random(p.id)
        skills = sorted(ctx.skills)
        drop = rng.choice(skills) if len(skills) > 1 else None
        pert = replace(ctx, skills=set(skills) - ({drop} if drop else set()))
        cp = CachedPersona(p, ctx, cands, jobs, pert)
        self._cache[p.id] = cp
        return cp

    def rank(self, cp: CachedPersona, w: Weights, perturbed: bool = False) -> list[Ranked]:
        ctx = cp.perturbed_ctx if perturbed else cp.ctx
        return finalize(score_candidates(cp.cands, cp.jobs, ctx, w), w)

    # ------------------------------------------------------------------ evaluation
    def evaluate(self, w: Weights, *, stability: bool = True, latency: bool = False) -> EvalResult:
        per: dict[str, dict[str, float]] = {}
        lists: dict[str, list[str]] = {}
        companies: dict[str, list[str]] = {}
        now = datetime.now(UTC)
        for p in self.personas:
            cp = self._prepare(p)
            ranked = self.rank(cp, w)
            ids = [str(r.job.id) for r in ranked]
            rel = self.qrels.get(p.id, {})
            cond = M.condense(ids, rel)
            top = ranked[:K]
            lists[p.id] = ids[:K]
            companies[p.id] = [r.job.company_name for r in top]
            row = {
                "ndcg@5": M.ndcg_at(cond, rel, 5),
                "ndcg@10": M.ndcg_at(cond, rel, 10),
                "ndcg@20": M.ndcg_at(cond, rel, 20),
                # Unjudged roles count as not relevant: a pessimistic bound that stops a
                # configuration winning by surfacing roles nobody has graded.
                "ndcg@10_strict": M.ndcg_at(ids, rel, 10),
                "p@10": M.precision_at(cond, rel, 10),
                "map": M.average_precision(cond, rel),
                "mrr": M.mrr_at(cond, {d for d, g in rel.items() if g >= M.REL}, 10),
                "bpref": M.bpref(ids, rel),
                "success@5": M.success_at(cond, rel, 5),
                "judged@10": M.judged_at(ids, rel, 10),
                "ild@10": M.intra_list_diversity(
                    [
                        np.asarray(r.job.embedding, dtype=np.float32)
                        if r.job.embedding is not None
                        else None
                        for r in top
                    ]
                ),
                "companies@10": len({r.job.company_name for r in top}) / max(1, len(top)),
                "median_age_days": statistics.median(
                    [
                        (
                            (now - (r.job.posted_at or r.job.first_seen_at or now)).total_seconds()
                            / 86400
                        )
                        for r in top
                    ]
                )
                if top
                else 0.0,
                "violations@10": violation_rate(p, top),
            }
            if stability:
                pert = [str(r.job.id) for r in self.rank(cp, w, perturbed=True)]
                row["stability_rbo"] = M.rbo(ids, pert, depth=K)
            if latency:
                row["latency_ms"] = self._latency(p, w)
            per[p.id] = row
        summary = summarize(per)
        summary["exposure_gini"] = {
            "mean": M.exposure_gini(list(companies.values())),
            "lo": 0,
            "hi": 0,
        }
        if self.catalogue is None:
            from sqlalchemy import func, select

            self.catalogue = (
                self.session.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(Job.status == "open", Job.is_tech.is_(True))
                )
                or 1
            )
        shown = {d for lst in lists.values() for d in lst}
        summary["coverage"] = {"mean": len(shown) / self.catalogue, "lo": 0, "hi": 0}
        return EvalResult(
            config=w.to_dict(),
            per_persona=per,
            summary=summary,
            segments=segment(per, self.personas),
            lists=lists,
        )

    def _latency(self, p: Persona, w: Weights, reps: int = 3) -> float:
        from app.search.engine import recommend

        ctx, f = context(p)
        times = []
        for _ in range(reps):
            t = time.perf_counter()
            recommend(self.session, ctx, f, limit=20, weights=w)
            times.append((time.perf_counter() - t) * 1000)
        return statistics.median(times)


def violation_rate(p: Persona, top: list[Ranked]) -> float:
    """Share of the top-k that breaks a hard expectation of the persona."""
    if not top:
        return 0.0
    bad = 0
    for r in top:
        j = r.job
        level_bad = (
            j.seniority is not None
            and p.levels
            and j.seniority not in p.levels
            and (
                (set(p.levels) <= EARLY and j.seniority in {"senior", "staff_plus"})
                or (not set(p.levels) & EARLY and j.seniority in EARLY)
            )
        )
        yoe_bad = j.min_yoe is not None and j.min_yoe > p.years + 2
        loc_ok = bool(set(j.cities or []) & set(p.cities)) or (
            j.remote_type == "remote"
            and (not j.countries or {"IN", "WW", "R:APAC"} & set(j.countries))
        )
        bad += bool(level_bad or yoe_bad or not loc_ok)
    return bad / len(top)


def summarize(per: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    out = {}
    metrics = next(iter(per.values())).keys() if per else []
    for m in metrics:
        vals = [row[m] for row in per.values() if m in row]
        mean, lo, hi = M.bootstrap_ci(vals)
        out[m] = {"mean": round(mean, 4), "lo": round(lo, 4), "hi": round(hi, 4)}
    return out


def segment(
    per: dict[str, dict[str, float]], personas: list[Persona]
) -> dict[str, dict[str, float]]:
    groups: dict[str, list[str]] = {}
    for p in personas:
        for g in p.groups:
            groups.setdefault(g, []).append(p.id)
    out = {}
    for g, ids in sorted(groups.items()):
        rows = [per[i] for i in ids if i in per]
        if rows:
            out[g] = {
                "n": len(rows),
                "ndcg@10": round(M.mean([r["ndcg@10"] for r in rows]), 4),
                "p@10": round(M.mean([r["p@10"] for r in rows]), 4),
                "violations@10": round(M.mean([r["violations@10"] for r in rows]), 4),
            }
    return out


def compare(
    a: EvalResult, b: EvalResult, metrics: tuple[str, ...] = ("ndcg@10", "p@10", "map", "bpref")
) -> dict:
    """Paired comparison of two configurations over the same personas."""
    ids = sorted(set(a.per_persona) & set(b.per_persona))
    out = {}
    for m in metrics:
        va = [a.per_persona[i][m] for i in ids]
        vb = [b.per_persona[i][m] for i in ids]
        out[m] = {
            "a": round(M.mean(va), 4),
            "b": round(M.mean(vb), 4),
            "delta": round(M.mean(vb) - M.mean(va), 4),
            "p_value": round(M.paired_randomization_test(vb, va), 4),
            "wins": sum(y > x for x, y in zip(va, vb, strict=True)),
            "losses": sum(y < x for x, y in zip(va, vb, strict=True)),
            "n": len(ids),
        }
    return out
