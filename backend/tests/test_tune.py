"""The tuning objective and the robust trial selection."""

from __future__ import annotations

from types import SimpleNamespace

from app.evals.tune import objective_value, persona_objective, robust_value


def _res(rows):
    return SimpleNamespace(per_persona={str(i): r for i, r in enumerate(rows)})


def _row(cond, strict, viol=0.0):
    return {"ndcg@10": cond, "ndcg@10_strict": strict, "violations@10": viol}


def test_unjudged_results_cost_score():
    # Same ordering of judged roles, but one list is padded with unjudged roles.
    assert persona_objective(_row(0.9, 0.9)) > persona_objective(_row(0.9, 0.5))


def test_violations_are_penalised():
    assert persona_objective(_row(0.8, 0.8, 0.2)) < persona_objective(_row(0.8, 0.8, 0.0))


def test_robust_value_prefers_consistent_gains():
    steady = _res([_row(0.7, 0.7)] * 6)
    spiky = _res([_row(1.0, 1.0)] * 2 + [_row(0.58, 0.58)] * 4)
    assert objective_value(spiky) > objective_value(steady)
    assert robust_value(steady) > robust_value(spiky)
