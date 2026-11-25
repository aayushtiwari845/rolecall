import numpy as np

from app.search.ltr import auc, fit_logistic


def test_logistic_recovers_the_informative_feature():
    rng = np.random.default_rng(1)
    X = rng.random((4000, 3))
    # Engagement depends on feature 1 only.
    p = 1 / (1 + np.exp(-(6 * X[:, 1] - 3)))
    y = (rng.random(4000) < p).astype(float)
    coef, _ = fit_logistic(X, y)
    assert coef[1] > 3 * abs(coef[0]) and coef[1] > 3 * abs(coef[2])
    assert auc(X @ coef, y) > 0.75


def test_auc_bounds():
    y = np.array([0, 0, 1, 1.0])
    assert auc(np.array([0.1, 0.2, 0.8, 0.9]), y) == 1.0
    assert auc(np.array([0.9, 0.8, 0.2, 0.1]), y) == 0.0
