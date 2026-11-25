import numpy as np
import pytest

from app.evals import metrics as m


def test_ndcg_perfect_and_reversed():
    rel = {"a": 3, "b": 2, "c": 0}
    assert m.ndcg_at(["a", "b", "c"], rel, 3) == pytest.approx(1.0)
    assert m.ndcg_at(["c", "b", "a"], rel, 3) < 0.7


def test_condensed_lists_skip_unjudged():
    rel = {"a": 3, "b": 0}
    assert m.condense(["x", "a", "y", "b"], rel) == ["a", "b"]
    assert m.judged_at(["x", "a", "y", "b"], rel, 4) == 0.5


def test_average_precision():
    rel = {"a": 3, "b": 0, "c": 2}
    assert m.average_precision(["a", "b", "c"], rel) == pytest.approx((1 + 2 / 3) / 2)


def test_bpref_ignores_unjudged_and_penalises_nonrelevant_first():
    rel = {"a": 3, "n": 0}
    assert m.bpref(["a", "n"], rel) == 1.0
    assert m.bpref(["n", "a"], rel) == 0.0
    assert m.bpref(["zz", "a", "n"], rel) == 1.0


def test_rbo_bounds():
    assert m.rbo(list("abcdefghij"), list("abcdefghij")) == pytest.approx(1.0)
    assert m.rbo(list("abcdefghij"), list("klmnopqrst")) == 0.0
    assert 0 < m.rbo(list("abcdefghij"), list("bacdefghij")) < 1


def test_diversity_and_gini():
    e = np.eye(3)
    assert m.intra_list_diversity([e[0], e[1], e[2]]) == pytest.approx(1.0)
    assert m.intra_list_diversity([e[0], e[0]]) == pytest.approx(0.0, abs=1e-6)
    assert m.gini([1, 1, 1, 1]) == pytest.approx(0.0)
    assert m.gini([0, 0, 0, 10]) > 0.7


def test_bootstrap_and_randomization():
    mean, lo, hi = m.bootstrap_ci([0.5] * 20)
    assert mean == lo == hi == 0.5
    a = [0.9] * 15
    b = [0.3] * 15
    assert m.paired_randomization_test(a, b) < 0.01
    assert m.paired_randomization_test(a, a) == 1.0
