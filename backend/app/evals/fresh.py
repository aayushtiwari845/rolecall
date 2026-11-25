"""The pre-registered comparison on fresh held-out personas (docs/evaluation.md, 5b).

The fresh personas were written after tuning, judged blind and are never used for
tuning. This module evaluates the released configuration against the tuned ranking
weights of each tuning round on them, once, and applies the decision rule fixed before
pooling: round 4's weights would ship if fresh nDCG@10 is not worse (delta >= -0.005)
and violations@10 do not rise.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.evals.judged import load_personas
from app.evals.recsys import Evaluator, compare
from app.search.rank import Weights, load_config

RESULTS = Path(__file__).resolve().parents[2] / "evals" / "results"
HISTORY = RESULTS / "tuning_history"
ROUNDS = {
    "round2_tuned": "round2_full_space.json",
    "round3_tuned": "round3_cv_full_space.json",
    "round4_tuned": "round4_cv_trust_region.json",
}
METRICS = ("ndcg@10", "ndcg@10_strict", "p@10", "bpref", "violations@10")
RETRIEVAL_KEYS = ("k_dense", "k_lex", "rrf_k", "w_lex", "rerank_head", "rerank_blend")


def _ranking_only(tuned: Weights, released: Weights) -> Weights:
    """Tuned ranking weights on the released retrieval, so only ranking differs."""
    return replace(tuned, **{k: getattr(released, k) for k in RETRIEVAL_KEYS})


def run(session: Session, write: bool = True) -> dict:
    personas = load_personas("fresh")
    released = load_config()
    configs = {"released": released}
    for name, file in ROUNDS.items():
        cfg = json.loads((HISTORY / file).read_text(encoding="utf-8"))["config"]
        configs[name] = _ranking_only(Weights.from_dict(cfg), released)

    ev = Evaluator(session, personas, retrieval=released)
    results = {name: ev.evaluate(w) for name, w in configs.items()}
    base = results["released"]

    report: dict = {
        "run_at": datetime.now(UTC).isoformat(),
        "personas": [p.id for p in personas],
        "summary": {n: r.summary for n, r in results.items()},
        "segments": {n: r.segments for n, r in results.items()},
        "per_persona": {n: r.per_persona for n, r in results.items()},
        "compare_vs_released": {
            n: compare(base, r, METRICS) for n, r in results.items() if n != "released"
        },
    }
    c = report["compare_vs_released"]["round4_tuned"]
    ships = c["ndcg@10"]["delta"] >= -0.005 and c["violations@10"]["delta"] <= 0.01
    report["decision"] = {
        "rule": "round 4 ships if fresh nDCG@10 delta >= -0.005 and violations@10 do not rise",
        "round4_ships": ships,
        "ndcg@10_delta": c["ndcg@10"]["delta"],
        "p_value": c["ndcg@10"]["p_value"],
    }
    if write:
        (RESULTS / "fresh_holdout.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def apply_decision(report: dict) -> dict | None:
    """Ship round 4's ranking weights if the pre-registered rule passed.

    Retrieval and search settings stay as released; only the ranking weights change.
    The decision and its fresh-persona evidence are recorded in ``tuned_config.json``.
    """
    from app.search.rank import TUNED_FILE

    if not report["decision"]["round4_ships"]:
        return None
    released = load_config()
    cfg = json.loads((HISTORY / ROUNDS["round4_tuned"]).read_text(encoding="utf-8"))["config"]
    out = _ranking_only(Weights.from_dict(cfg), released)
    data = json.loads(TUNED_FILE.read_text(encoding="utf-8"))
    data["decisions"]["ranking"] = {
        **data["decisions"]["ranking"],
        "ships": True,
        "decided_by": "fresh held-out personas (pre-registered, docs/evaluation.md 5b)",
        "fresh_ndcg@10_delta": report["decision"]["ndcg@10_delta"],
        "fresh_p_value": report["decision"]["p_value"],
        "fresh_personas": len(report["personas"]),
    }
    data["config"] = out.to_dict()
    data["released_config"] = out.to_dict()
    TUNED_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    load_config.cache_clear()
    return data
