"""Run eval suites, store results in Postgres (shown on /evals) and in evals/results/."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from app.db import session_scope
from app.models import EvalRun

RESULTS = Path(__file__).resolve().parents[2] / "evals" / "results"


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, timeout=5
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def run_suite(suite: str, use_llm: bool = True, **kw) -> dict:
    from app.evals import agent, extraction, recommendation, retrieval

    with session_scope() as s:
        if suite == "retrieval":
            res = retrieval.run(s, use_llm=use_llm, **kw)
        elif suite == "recommendation":
            res = recommendation.run(s, use_llm=use_llm, **kw)
        elif suite == "extraction":
            res = extraction.run(use_llm=use_llm)
        elif suite == "agent":
            res = agent.run(s)
        elif suite == "recsys":
            res = _recsys(s)
        else:
            raise ValueError(f"unknown suite {suite}")
        sha = _git_sha()
        for variant, metrics in res.items():
            s.add(
                EvalRun(
                    suite=suite,
                    variant=variant,
                    metrics=metrics,
                    config={"git_sha": sha, "use_llm": use_llm, **kw},
                )
            )
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{suite}.json").write_text(
        json.dumps(
            {
                "suite": suite,
                "run_at": datetime.now(UTC).isoformat(),
                "git_sha": sha,
                "results": res,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return res


def _recsys(session) -> dict:
    """Judged feed evaluation on held-out test personas: default vs shipped config."""
    from app.evals.judged import load_personas
    from app.evals.recsys import Evaluator, compare
    from app.search.rank import Weights, load_config

    ev = Evaluator(session, load_personas("test"))
    default, current = ev.evaluate(Weights(), latency=True), ev.evaluate(load_config(), latency=True)
    keep = ("ndcg@10", "p@10", "map", "bpref", "success@5", "violations@10", "ild@10",
            "companies@10", "stability_rbo", "judged@10", "latency_ms")

    def row(r):
        out = {k: r.summary[k]["mean"] for k in keep if k in r.summary}
        out["ndcg@10_95ci"] = f"{r.summary['ndcg@10']['lo']:.3f}-{r.summary['ndcg@10']['hi']:.3f}"
        out["personas"] = len(r.per_persona)
        return out

    res = {"hand_set_defaults": row(default)}
    if current.config != default.config:
        res["tuned"] = row(current)
        res["tuned"]["p_value_vs_defaults"] = compare(default, current)["ndcg@10"]["p_value"]
    return res
