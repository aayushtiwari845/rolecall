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
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, timeout=5).strip()
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
        else:
            raise ValueError(f"unknown suite {suite}")
        sha = _git_sha()
        for variant, metrics in res.items():
            s.add(EvalRun(suite=suite, variant=variant, metrics=metrics, config={"git_sha": sha, "use_llm": use_llm, **kw}))
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{suite}.json").write_text(
        json.dumps({"suite": suite, "run_at": datetime.now(UTC).isoformat(), "git_sha": sha, "results": res}, indent=2),
        encoding="utf-8",
    )
    return res
