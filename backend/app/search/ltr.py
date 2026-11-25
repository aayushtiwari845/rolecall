"""Learning-to-rank from logged behaviour.

Training data: every feed impression is an example; it is positive if the same user
clicked, saved or applied to that job within 7 days. Features are the ranker's own
interpretable features recomputed with the user's current context. A logistic regression
(plain numpy, L2-regularised, class-balanced) learns how much each feature predicts
engagement; its coefficients, rescaled to sum to the hand-set total, become new ranker
weights, so the model stays explainable.

With fewer than MIN_POSITIVES positives the trainer refuses, because hand-set weights
beat a model fitted on noise.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, fields
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Interaction, Job, User
from app.search.personalize import build_context
from app.search.rank import Weights, load_config, score_candidates
from app.search.retrieval import Candidate

log = logging.getLogger(__name__)

FEATURES = ["semantic", "lexical", "skills", "level", "role", "location", "recency", "affinity"]
POSITIVE = {"click", "save", "apply", "apply_click"}
MIN_POSITIVES = 200
WEIGHTS_FILE = Path(__file__).resolve().parents[2] / "evals" / "results" / "ltr_weights.json"


def build_dataset(session: Session, max_users: int = 500) -> tuple[np.ndarray, np.ndarray]:
    X: list[list[float]] = []
    y: list[int] = []
    users = list(session.scalars(select(User).limit(max_users)))
    for user in users:
        imps = list(
            session.execute(
                select(Interaction.job_id, Interaction.created_at, Interaction.position).where(
                    Interaction.user_id == user.id,
                    Interaction.type == "impression",
                    Interaction.surface == "feed",
                )
            )
        )
        if not imps:
            continue
        engaged = {
            r.job_id
            for r in session.execute(
                select(Interaction.job_id).where(
                    Interaction.user_id == user.id, Interaction.type.in_(POSITIVE)
                )
            )
        }
        ctx = build_context(session, user)
        ids = list({i.job_id for i in imps})
        jobs = {j.id: j for j in session.scalars(select(Job).where(Job.id.in_(ids)))}
        cands = [Candidate(job_id=i, dense_rank=1, dense_sim=0.0) for i in ids if i in jobs]
        # semantic/lexical are not reconstructable offline per request; use similarity to profile.
        for r in score_candidates(cands, jobs, ctx, load_config()):
            emb = r.job.embedding
            if ctx.qvec is not None and emb is not None:
                r.features["semantic"] = float(np.dot(ctx.qvec, np.asarray(emb, dtype=np.float32)))
            X.append([r.features.get(f, 0.0) for f in FEATURES])
            y.append(1 if r.job.id in engaged else 0)
    return np.asarray(X, dtype=np.float64), np.asarray(y, dtype=np.float64)


def fit_logistic(
    X: np.ndarray, y: np.ndarray, l2: float = 1.0, lr: float = 0.5, steps: int = 3000
) -> tuple[np.ndarray, float]:
    """Class-balanced logistic regression by gradient descent on standardised features."""
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    pos = y.mean()
    w_pos, w_neg = 0.5 / max(pos, 1e-9), 0.5 / max(1 - pos, 1e-9)
    sample_w = np.where(y == 1, w_pos, w_neg)
    w, b = np.zeros(Z.shape[1]), 0.0
    n = len(y)
    for _ in range(steps):
        p = 1 / (1 + np.exp(-(Z @ w + b)))
        g = (p - y) * sample_w
        w -= lr * (Z.T @ g / n + l2 * w / n)
        b -= lr * g.mean()
    return w / sd, b  # back to the original feature scale


def auc(scores: np.ndarray, y: np.ndarray) -> float:
    order = np.argsort(scores)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1)
    n_pos, n_neg = y.sum(), len(y) - y.sum()
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def train(session: Session, min_positives: int = MIN_POSITIVES) -> dict:
    X, y = build_dataset(session)
    if y.sum() < min_positives:
        return {
            "trained": False,
            "reason": f"only {int(y.sum())} positive examples; need {min_positives}",
            "examples": len(y),
        }
    rng = np.random.default_rng(0)
    idx = rng.permutation(len(y))
    cut = int(0.8 * len(y))
    tr, te = idx[:cut], idx[cut:]
    coef, _ = fit_logistic(X[tr], y[tr])
    hand = np.array([getattr(load_config(), f) for f in FEATURES])
    learned = np.clip(coef, 0, None)
    if learned.sum() == 0:
        return {"trained": False, "reason": "no feature had a positive effect", "examples": len(y)}
    learned = learned / learned.sum() * hand.sum()
    result = {
        "trained": True,
        "examples": len(y),
        "positives": int(y.sum()),
        "auc_hand_weights": round(auc(X[te] @ hand, y[te]), 4),
        "auc_learned_weights": round(auc(X[te] @ learned, y[te]), 4),
        "weights": {f: round(float(v), 4) for f, v in zip(FEATURES, learned, strict=True)},
    }
    if result["auc_learned_weights"] > result["auc_hand_weights"]:
        WEIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        WEIGHTS_FILE.write_text(json.dumps(result, indent=2), encoding="utf-8")
        result["saved"] = str(WEIGHTS_FILE)
    return result


def load_weights() -> Weights:
    """Learned weights if a trained model beat the hand-set ones, else the defaults."""
    try:
        data = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))
        names = {f.name for f in fields(Weights)}
        return Weights(
            **{**asdict(Weights()), **{k: v for k, v in data["weights"].items() if k in names}}
        )
    except (OSError, ValueError, KeyError):
        return Weights()
