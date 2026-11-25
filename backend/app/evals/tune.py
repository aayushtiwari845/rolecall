"""Hyperparameter optimisation for the feed ranker.

Stage 1, retrieval: grid over candidate pool sizes (dense and lexical depth). Metric is
candidate recall: the share of judged-relevant roles (grade >= 2) that reach the
candidate set at all, against retrieval latency. The smallest pool within 1% of the best
recall wins: more candidates cost latency and cannot be ranked if never retrieved.

Stage 2, ranking: Optuna TPE over 22 scoring parameters (feature weights, feature
shapes, experience penalty, diversity), on dev personas only. Objective:
    condensed nDCG@10 - 0.5 * violations@10 - 0.5 * max(0, 0.6 - judged@10)
so a configuration cannot win by breaking hard expectations or by hiding in unjudged
documents. The study is seeded and reproducible.

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


def objective_value(res) -> float:
    s = res.summary
    return (
        s["ndcg@10"]["mean"]
        - 0.5 * s["violations@10"]["mean"]
        - 0.5 * max(0.0, 0.6 - s["judged@10"]["mean"])
    )


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


def tune_ranking(
    session: Session, base: Weights, trials: int = 300, seed: int = 7
) -> tuple[Weights, object, Evaluator]:
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    dev = Evaluator(session, load_personas("dev"), retrieval=base)

    def objective(trial) -> float:
        res = dev.evaluate(suggest(trial, base), stability=False)
        for k in ("ndcg@10", "violations@10", "judged@10", "ild@10"):
            trial.set_user_attr(k, res.summary[k]["mean"])
        return objective_value(res)

    study = optuna.create_study(
        direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed, multivariate=True)
    )
    study.enqueue_trial(
        {
            k: getattr(base, k)
            for k in (
                "semantic",
                "skills",
                "level",
                "role",
                "location",
                "recency",
                "affinity",
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
            )
        }
    )  # trial 0 = current defaults, so the search can only match or improve on them
    study.optimize(objective, n_trials=trials, show_progress_bar=False)
    best = suggest(optuna.trial.FixedTrial(study.best_params), base)
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


def run(session: Session, trials: int = 300, seed: int = 7, write: bool = True) -> dict:
    current = load_config()
    retrieval = tune_retrieval(session)
    base = replace(
        current, k_dense=retrieval["choice"]["k_dense"], k_lex=retrieval["choice"]["k_lex"]
    )
    best, study, dev = tune_ranking(session, base, trials=trials, seed=seed)

    test = Evaluator(session, load_personas("test"), retrieval=base)
    res_default_dev = dev.evaluate(current, latency=True)
    res_best_dev = dev.evaluate(best, latency=True)
    res_default_test = test.evaluate(current, latency=True)
    res_best_test = test.evaluate(best, latency=True)
    cmp_test = compare(res_default_test, res_best_test)
    cmp_dev = compare(res_default_dev, res_best_dev)

    # Ship only if the tuned config is not worse on personas it never saw.
    d = cmp_test["ndcg@10"]
    ships = (
        d["delta"] >= -0.005
        and res_best_test.mean("violations@10") <= res_default_test.mean("violations@10") + 0.01
    )
    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "git_sha": _sha(),
        "trials": trials,
        "seed": seed,
        "objective": "ndcg@10 - 0.5*violations@10 - 0.5*max(0, 0.6 - judged@10)",
        "retrieval_stage": retrieval,
        "param_importance": importance(study),
        "best_trial": study.best_trial.number,
        "best_objective_dev": round(study.best_value, 4),
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
        "shipped": ships,
        "config": best.to_dict(),
    }
    if write and ships:
        TUNED_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
        load_config.cache_clear()
    return report
