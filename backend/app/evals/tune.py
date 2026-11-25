"""Hyperparameter optimisation for the feed ranker.

Stage 1, retrieval: grid over candidate pool sizes (dense and lexical depth). Metric is
candidate recall: the share of judged-relevant roles (grade >= 2) that reach the
candidate set at all, against retrieval latency. The smallest pool within 1% of the best
recall wins: more candidates cost latency and cannot be ranked if never retrieved.

Stage 2, ranking: Optuna TPE over 22 scoring parameters (feature weights, feature
shapes, experience penalty, diversity), on dev personas only. Objective:
    0.5 * condensed nDCG@10 + 0.5 * strict nDCG@10 - 0.5 * violations@10
Condensed nDCG (unjudged roles removed) rewards ordering the judged roles well; strict
nDCG (unjudged roles count as 0) stops a configuration winning by surfacing roles nobody
graded; the violation term stops it breaking hard expectations. The study is seeded.

Selection: the trial with the best objective is prone to the winner's curse on ten
personas, so the ten best trials are re-scored per persona and the one with the highest
lower bound (mean - standard error) is chosen: a smaller gain that holds across personas
beats a larger one carried by two of them.

Selection: the best trial is compared with the current defaults on the held-out test
personas with a paired randomisation test. It ships (``tuned_config.json``) only if it is
not worse on test; the file records dev and test metrics, the search space and the seed.
"""

from __future__ import annotations

import json
import logging
import statistics
import subprocess
import time
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.evals.judged import context, load_personas, load_qrels
from app.evals.recsys import Evaluator, compare
from app.search.engine import _retrieve
from app.search.rank import TUNED_FILE, Weights, load_config

log = logging.getLogger(__name__)


OBJECTIVE = "0.5*ndcg@10 + 0.5*ndcg@10_strict - 0.5*violations@10"


def persona_objective(row: dict) -> float:
    return 0.5 * row["ndcg@10"] + 0.5 * row["ndcg@10_strict"] - 0.5 * row["violations@10"]


def objective_value(res) -> float:
    return statistics.fmean(persona_objective(r) for r in res.per_persona.values())


def robust_value(res) -> float:
    """Mean minus standard error of the per-persona objective."""
    vals = [persona_objective(r) for r in res.per_persona.values()]
    se = statistics.stdev(vals) / len(vals) ** 0.5 if len(vals) > 1 else 0.0
    return statistics.fmean(vals) - se


# ------------------------------------------------------------------ stage 1
def tune_retrieval(session: Session, split: str = "dev") -> dict:
    personas = load_personas(split)
    qrels = load_qrels()
    grid = [(kd, kl) for kd in (100, 200, 300, 500) for kl in (0, 50, 150, 300)]
    rows = []
    for kd, kl in grid:
        w = replace(Weights(), k_dense=kd, k_lex=kl)
        recalls, lat = [], []
        for p in personas:
            ctx, f = context(p)
            relevant = {d for d, g in qrels.get(p.id, {}).items() if g >= 2}
            t = time.perf_counter()
            cands = _retrieve(session, ctx, f, w, "hybrid")
            lat.append((time.perf_counter() - t) * 1000)
            got = {str(c.job_id) for c in cands}
            if relevant:
                recalls.append(len(got & relevant) / len(relevant))
        rows.append(
            {
                "k_dense": kd,
                "k_lex": kl,
                "candidate_recall": round(statistics.mean(recalls), 4),
                "p50_ms": round(statistics.median(lat), 1),
            }
        )
    best = max(r["candidate_recall"] for r in rows)
    ok = [r for r in rows if r["candidate_recall"] >= best - 0.01]
    choice = min(ok, key=lambda r: (r["p50_ms"], r["k_dense"] + r["k_lex"]))
    return {"grid": rows, "choice": choice}


# ------------------------------------------------------------------ stage 2
def suggest(trial, base: Weights) -> Weights:
    s = trial.suggest_float
    return replace(
        base,
        semantic=s("semantic", 0.0, 1.0),
        skills=s("skills", 0.0, 1.0),
        level=s("level", 0.0, 1.0),
        role=s("role", 0.0, 0.6),
        location=s("location", 0.0, 0.4),
        recency=s("recency", 0.0, 0.4),
        affinity=s("affinity", 0.0, 0.2),
        sim_floor=s("sim_floor", 0.3, 0.65),
        sim_span=s("sim_span", 0.15, 0.5),
        skill_saturation=trial.suggest_int("skill_saturation", 2, 10),
        level_adjacent=s("level_adjacent", 0.0, 0.9),
        level_two_away=s("level_two_away", 0.0, 0.5),
        level_unknown=s("level_unknown", 0.2, 0.95),
        role_adjacent=s("role_adjacent", 0.3, 1.0),
        role_other=s("role_other", 0.0, 0.7),
        recency_tau_days=s("recency_tau_days", 3.0, 120.0, log=True),
        yoe_slack=s("yoe_slack", 0.0, 3.0),
        yoe_step=s("yoe_step", 0.05, 0.6),
        yoe_floor=s("yoe_floor", 0.0, 0.8),
        mmr_lambda=s("mmr_lambda", 0.6, 1.0),
        max_per_company=trial.suggest_int("max_per_company", 1, 5),
        diversity_window=trial.suggest_categorical("diversity_window", [10, 20]),
    )


FEATURES = ("semantic", "skills", "level", "role", "location", "recency", "affinity")


def suggest_trust(trial, base: Weights) -> Weights:
    """A trust region around ``base``: the feature weights within half to one and a half
    times their value, plus four shape parameters in tight ranges. Twelve parameters
    instead of twenty-two, none far from a sensible prior."""
    s = trial.suggest_float
    feats = {k: s(k, 0.5 * getattr(base, k), 1.5 * getattr(base, k)) for k in FEATURES}
    return replace(
        base,
        **feats,
        sim_floor=s("sim_floor", base.sim_floor - 0.05, base.sim_floor + 0.05),
        level_unknown=s(
            "level_unknown", max(0.2, base.level_unknown - 0.15), base.level_unknown + 0.15
        ),
        yoe_step=s("yoe_step", 0.5 * base.yoe_step, 1.5 * base.yoe_step),
        mmr_lambda=s("mmr_lambda", 0.85, 1.0),
        max_per_company=trial.suggest_int("max_per_company", 1, 3),
    )


SPACES = {"full": suggest, "trust_region": suggest_trust}
SPACE_PARAMS = {
    "full": FEATURES
    + (
        "sim_floor",
        "sim_span",
        "skill_saturation",
        "level_adjacent",
        "level_two_away",
        "level_unknown",
        "role_adjacent",
        "role_other",
        "recency_tau_days",
        "yoe_slack",
        "yoe_step",
        "yoe_floor",
        "mmr_lambda",
        "max_per_company",
        "diversity_window",
    ),
    "trust_region": FEATURES
    + ("sim_floor", "level_unknown", "yoe_step", "mmr_lambda", "max_per_company"),
}


def _study(ev: Evaluator, base: Weights, space: str, trials: int, seed: int):
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    fn = SPACES[space]

    def objective(trial) -> float:
        res = ev.evaluate(fn(trial, base), stability=False)
        for k in ("ndcg@10", "violations@10", "judged@10", "ild@10"):
            trial.set_user_attr(k, res.summary[k]["mean"])
        return objective_value(res)

    study = optuna.create_study(
        direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed, multivariate=True)
    )
    # Trial 0 = current defaults, so the search can only match or improve on them.
    study.enqueue_trial({k: getattr(base, k) for k in SPACE_PARAMS[space]})
    study.optimize(objective, n_trials=trials, show_progress_bar=False)
    return study


def _select(study, ev: Evaluator, base: Weights, space: str) -> tuple[Weights, list]:
    """Re-score the ten best trials and keep the one with the highest lower bound."""
    import optuna

    done = [t for t in study.trials if t.value is not None]
    top = sorted(done, key=lambda t: t.value, reverse=True)[:10]
    scored = []
    for t in top:
        w = SPACES[space](optuna.trial.FixedTrial(t.params), base)
        scored.append((robust_value(ev.evaluate(w, stability=False)), t.number, w))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[0][2], scored


def cross_validate(
    ev: Evaluator, base: Weights, space: str, folds: int = 5, trials: int = 150, seed: int = 7
) -> dict:
    """Nested cross-validation of the tuning *procedure* inside the dev personas.

    Each fold tunes on the other personas and scores the held-out ones, so every persona
    gets a held-out (tuned - default) objective. A search space that only helps on the
    personas it was tuned on shows up here as a non-positive mean.
    """
    from app.evals.metrics import bootstrap_ci, paired_randomization_test

    ids = sorted(p.id for p in ev.personas)
    tuned: dict[str, float] = {}
    default: dict[str, float] = {}
    for f in range(folds):
        held = set(ids[f::folds])
        train, test = ev.subset(set(ids) - held), ev.subset(held)
        w, _ = _select(_study(train, base, space, trials, seed + f), train, base, space)
        for pid, row in test.evaluate(w, stability=False).per_persona.items():
            tuned[pid] = persona_objective(row)
        for pid, row in test.evaluate(base, stability=False).per_persona.items():
            default[pid] = persona_objective(row)
    a = [default[i] for i in ids]
    b = [tuned[i] for i in ids]
    deltas = [y - x for x, y in zip(a, b, strict=True)]
    mean, lo, hi = bootstrap_ci(deltas)
    return {
        "space": space,
        "folds": folds,
        "trials_per_fold": trials,
        "heldout_delta": {"mean": round(mean, 4), "lo": round(lo, 4), "hi": round(hi, 4)},
        "p_value": round(paired_randomization_test(a, b), 4),
        "wins": sum(d > 1e-9 for d in deltas),
        "losses": sum(d < -1e-9 for d in deltas),
        "per_persona": {i: round(d, 4) for i, d in zip(ids, deltas, strict=True)},
    }


def tune_ranking(
    session: Session, base: Weights, trials: int = 300, seed: int = 7, space: str = "full"
) -> tuple[Weights, object, Evaluator]:
    dev = Evaluator(session, load_personas("dev"), retrieval=base)
    study = _study(dev, base, space, trials, seed)
    best, scored = _select(study, dev, base, space)
    study.set_user_attr("selection", [{"trial": n, "robust": round(v, 4)} for v, n, _ in scored])
    study.set_user_attr("top_configs", [w.to_dict() for _, _, w in scored[:5]])
    study.set_user_attr("chosen_trial", scored[0][1])
    return best, study, dev


def importance(study) -> dict[str, float]:
    try:
        import optuna

        return {k: round(v, 3) for k, v in optuna.importance.get_param_importances(study).items()}
    except Exception:  # noqa: BLE001 - needs enough completed trials
        return {}


def _sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, timeout=5
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def run(
    session: Session, trials: int = 300, seed: int = 7, write: bool = True, cv_trials: int = 150
) -> dict:
    current = load_config()
    retrieval = tune_retrieval(session)
    base = replace(
        current, k_dense=retrieval["choice"]["k_dense"], k_lex=retrieval["choice"]["k_lex"]
    )
    # Which search space generalises? Nested CV inside dev decides, before test is used.
    dev_ev = Evaluator(session, load_personas("dev"), retrieval=base)
    cv = {sp: cross_validate(dev_ev, base, sp, trials=cv_trials, seed=seed) for sp in SPACES}
    # Same principle as trial selection: the space whose held-out gain has the higher
    # lower bound, not the higher mean.
    space = max(cv, key=lambda sp: cv[sp]["heldout_delta"]["lo"])
    best, study, dev = tune_ranking(session, base, trials=trials, seed=seed, space=space)

    test = Evaluator(session, load_personas("test"), retrieval=base)
    res_default_dev = dev.evaluate(current, latency=True)
    res_best_dev = dev.evaluate(best, latency=True)
    res_default_test = test.evaluate(current, latency=True)
    res_best_test = test.evaluate(best, latency=True)
    cmp_test = compare(res_default_test, res_best_test)
    cmp_dev = compare(res_default_dev, res_best_dev)

    search = tune_search(session)
    search_summary = {k: v for k, v in search.items() if k != "grid"}
    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "git_sha": _sha(),
        "trials": trials,
        "seed": seed,
        "objective": OBJECTIVE,
        "retrieval_stage": retrieval,
        "cross_validation": cv,
        "space": space,
        "param_importance": importance(study),
        "best_trial": study.best_trial.number,
        "best_objective_dev": round(study.best_value, 4),
        "selection": study.user_attrs.get("selection"),
        "chosen_trial": study.user_attrs.get("chosen_trial"),
        "top_configs": study.user_attrs.get("top_configs"),
        "dev": {
            "default": res_default_dev.summary,
            "tuned": res_best_dev.summary,
            "compare": cmp_dev,
        },
        "test": {
            "default": res_default_test.summary,
            "tuned": res_best_test.summary,
            "compare": cmp_test,
            "segments_default": res_default_test.segments,
            "segments_tuned": res_best_test.segments,
        },
        "search_stage": search_summary,
        "config": best.to_dict(),
    }
    return release(session, report, current, write=write)


def release(session: Session, report: dict, current: Weights, write: bool = True) -> dict:
    """Decide stage by stage what ships, and write ``tuned_config.json``.

    The three stages change independent parts of the config, so each is accepted or
    rejected on its own evidence from personas or queries it was not tuned on:

    - retrieval depth: the current ranking with the new depth must not be worse on test
      personas (nDCG@10 delta >= -0.005, no added violations);
    - ranking weights: held-out CV gain inside dev must be positive and the tuned weights
      must not be worse on test personas;
    - search: a setting over the latency budget is not eligible. The best affordable
      setting ships if the current one is over budget and the new one is not
      significantly worse on test queries (p >= 0.05), or if it is at least as good.
    """
    decisions: dict[str, dict] = {}
    out = current

    # Stage 1: retrieval depth, judged with the current ranking weights.
    choice = report["retrieval_stage"]["choice"]
    depth = replace(current, k_dense=choice["k_dense"], k_lex=choice["k_lex"])
    test = Evaluator(session, load_personas("test"), retrieval=current)
    test_depth = Evaluator(session, load_personas("test"), retrieval=depth)
    a, b = test.evaluate(current, latency=True), test_depth.evaluate(depth, latency=True)
    c = compare(a, b)["ndcg@10"]
    ok = c["delta"] >= -0.005 and b.mean("violations@10") <= a.mean("violations@10") + 0.01
    decisions["retrieval"] = {
        "ships": ok,
        "k_dense": choice["k_dense"],
        "k_lex": choice["k_lex"],
        "test_ndcg@10": [a.mean("ndcg@10"), b.mean("ndcg@10")],
        "p_value": c["p_value"],
        "latency_ms": [round(a.mean("latency_ms"), 1), round(b.mean("latency_ms"), 1)],
    }
    if ok:
        out = replace(out, k_dense=choice["k_dense"], k_lex=choice["k_lex"])

    # Stage 2: ranking weights.
    cv = report["cross_validation"][report["space"]]["heldout_delta"]["mean"]
    t = report["test"]["compare"]["ndcg@10"]
    vt = report["test"]["tuned"]["violations@10"]["mean"]
    vd = report["test"]["default"]["violations@10"]["mean"]
    ok = cv > 0 and t["delta"] >= -0.005 and vt <= vd + 0.01
    decisions["ranking"] = {
        "ships": ok,
        "space": report["space"],
        "cv_heldout_delta": cv,
        "test_ndcg@10_delta": t["delta"],
        "p_value": t["p_value"],
    }
    if ok:
        tuned = Weights.from_dict(report["config"])
        keep = {
            k: getattr(out, k)
            for k in ("k_dense", "k_lex", "rrf_k", "w_lex", "rerank_head", "rerank_blend")
        }
        out = replace(tuned, **keep)

    # Stage 3: free-text search fusion and reranking.
    ss = report["search_stage"]
    budget = ss["latency_budget_ms"]
    over = ss["default"]["rerank_ms_est"] > budget
    sb, sd = ss["test_mrr@10"]["best"][0], ss["test_mrr@10"]["default"][0]
    p_val = ss["test_mrr@10"]["p_value"]
    ok = sb >= sd - 0.005 or (over and p_val >= 0.05)
    decisions["search"] = {
        "ships": ok,
        "current_over_budget": over,
        "test_mrr@10": [round(sd, 4), round(sb, 4)],
        "p_value": p_val,
        "setting": {k: ss["best"][k] for k in ("rrf_k", "w_lex", "rerank_head", "rerank_blend")},
    }
    if ok:
        out = replace(out, **decisions["search"]["setting"])

    report["decisions"] = decisions
    report["shipped"] = any(d["ships"] for d in decisions.values())
    report["released_config"] = out.to_dict()
    if write and report["shipped"]:
        TUNED_FILE.write_text(
            json.dumps({**report, "config": out.to_dict()}, indent=2), encoding="utf-8"
        )
        load_config.cache_clear()
    return report


# ------------------------------------------------------------------ stage 3 (search)
def tune_search(session: Session, n_queries: int = 160, seed: int = 11) -> dict:
    """Grid over fusion and reranking for free-text search, on known-item queries.

    Dense and lexical hits and cross-encoder scores are cached per query, so each grid
    point is evaluated without touching the database or the model again. The rerank
    head is capped by a latency budget measured on this machine.
    """
    import math
    import random

    import numpy as np
    from sqlalchemy import select

    from app.enrich.embed import embed_query, rerank
    from app.evals.metrics import bootstrap_ci, mrr_at, recall_at
    from app.evals.retrieval import sample_jobs, template_query
    from app.models import Job
    from app.search.engine import _load_jobs
    from app.search.filters import JobFilters
    from app.search.rank import UserContext, score_candidates
    from app.search.retrieval import dense, fuse, lexical

    rng = random.Random(seed)
    jobs = sample_jobs(session, n_queries, seed)
    cases = []
    # sample_jobs interleaves role families round-robin, so a plain i % 2 split would put
    # whole families on one side. Alternate within each family instead.
    seen_family: dict[str, int] = {}
    for j in jobs:
        fam = j.role_family or "swe"
        nth = seen_family[fam] = seen_family.get(fam, -1) + 1
        q = template_query(j, rng)
        dupes = {str(x) for x in session.scalars(select(Job.id).where(Job.duplicate_of == j.id))}
        d = dense(session, embed_query(q), JobFilters(), 150)
        lx = lexical(session, q, JobFilters(), 150)
        cases.append(
            {
                "q": q,
                "rel": {str(j.id)} | dupes,
                "d": d,
                "lx": lx,
                "split": "dev" if nth % 2 == 0 else "test",
                "rr": {},
            }
        )

    def doc(job) -> str:
        return f"{job.title} at {job.company_name}. {' '.join((job.skills or [])[:10])}. {(job.description_text or '')[:400]}"

    def run_case(c, rrf_k, w_lex, head, blend):
        fused = fuse(c["d"], c["lx"], 1.0, w_lex, rrf_k)
        if not fused:
            return []
        loaded = _load_jobs(session, [x.job_id for x in fused[:200]])
        fused = [x for x in fused if x.job_id in loaded]
        top = max(x.rrf for x in fused) or 1.0
        relv = {x.job_id: x.rrf / top for x in fused}
        if head:
            need = [x for x in fused[:head] if x.job_id not in c["rr"]]
            if need:
                for x, s in zip(
                    need, rerank(c["q"], [doc(loaded[x.job_id]) for x in need]), strict=True
                ):
                    c["rr"][x.job_id] = 1 / (1 + math.exp(-s))
            for x in fused[:head]:
                relv[x.job_id] = (1 - blend) * relv[x.job_id] + blend * c["rr"][x.job_id]
            for x in fused[head:]:
                relv[x.job_id] *= 1 - blend
        w = replace(
            Weights(),
            semantic=0.7,
            lexical=0,
            skills=0,
            level=0,
            role=0,
            location=0.03,
            recency=0.07,
            affinity=0,
            diversify=False,
        )
        return [
            str(r.job.id) for r in score_candidates(fused, loaded, UserContext(), w, relevance=relv)
        ]

    # Latency of the cross-encoder per document on this machine.
    # Measured on real documents of the shape search sends, after a warm-up call, as the
    # median of five batches of the head size most likely to fit.
    probe = [doc(j) for j in jobs[:20]]
    rerank(cases[0]["q"], probe[:2])
    runs = []
    for c in cases[:5]:
        t = time.perf_counter()
        rerank(c["q"], probe)
        runs.append((time.perf_counter() - t) * 1000 / len(probe))
    per_doc_ms = statistics.median(runs)

    grid = []
    for rrf_k in (10, 30, 60, 100):
        for w_lex in (0.5, 1.0, 2.0):
            for head, blend in [(0, 0.0)] + [
                (h, b) for h in (10, 20, 40) for b in (0.4, 0.65, 0.85)
            ]:
                dev_mrr, dev_r10 = [], []
                for c in (c for c in cases if c["split"] == "dev"):
                    ranked = run_case(c, rrf_k, w_lex, head, blend)
                    dev_mrr.append(mrr_at(ranked, c["rel"], 10))
                    dev_r10.append(recall_at(ranked, c["rel"], 10))
                grid.append(
                    {
                        "rrf_k": rrf_k,
                        "w_lex": w_lex,
                        "rerank_head": head,
                        "rerank_blend": blend,
                        "dev_mrr@10": round(float(np.mean(dev_mrr)), 4),
                        "dev_recall@10": round(float(np.mean(dev_r10)), 4),
                        "rerank_ms_est": round(head * per_doc_ms, 1),
                    }
                )
    budget_ms = 250.0
    affordable = [g for g in grid if g["rerank_ms_est"] <= budget_ms]
    best = max(affordable, key=lambda g: (g["dev_mrr@10"], -g["rerank_ms_est"]))
    default = next(
        g
        for g in grid
        if g["rrf_k"] == 60
        and g["w_lex"] == 1.0
        and g["rerank_head"] == 40
        and g["rerank_blend"] == 0.65
    )

    def test_scores(g):
        return [
            mrr_at(
                run_case(c, g["rrf_k"], g["w_lex"], g["rerank_head"], g["rerank_blend"]),
                c["rel"],
                10,
            )
            for c in cases
            if c["split"] == "test"
        ]

    from app.evals.metrics import paired_randomization_test

    tb, td = test_scores(best), test_scores(default)
    return {
        "queries": len(cases),
        "per_doc_rerank_ms": round(per_doc_ms, 2),
        "latency_budget_ms": budget_ms,
        "best": best,
        "default": default,
        "test_mrr@10": {
            "default": bootstrap_ci(td),
            "best": bootstrap_ci(tb),
            "p_value": paired_randomization_test(tb, td),
        },
        "grid": grid,
    }
