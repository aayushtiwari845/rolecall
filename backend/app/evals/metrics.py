"""IR and recommender metrics, plus the statistics needed to compare systems honestly.

Ranking metrics take ``ranked`` (list of ids) and ``rel`` (id -> graded relevance 0-3).
"Condensed" variants drop unjudged ids before cutting at k (Sakai 2007), which keeps
comparisons fair when a new ranker surfaces documents nobody has judged yet; ``judged_at``
reports how much of the top-k was judged so the gap stays visible.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Hashable, Sequence

import numpy as np

REL = 2  # grade at or above which a document counts as relevant for binary metrics


def recall_at(ranked: Sequence[Hashable], relevant: set, k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def mrr_at(ranked: Sequence[Hashable], relevant: set, k: int) -> float:
    for i, item in enumerate(ranked[:k], 1):
        if item in relevant:
            return 1.0 / i
    return 0.0


def condense(ranked: Sequence[Hashable], rel: dict) -> list:
    return [d for d in ranked if d in rel]


def precision_at(ranked: Sequence[Hashable], rel: dict, k: int, threshold: int = REL) -> float:
    top = ranked[:k]
    if not top:
        return 0.0
    return sum(1 for i in top if rel.get(i, 0) >= threshold) / k


def dcg(gains: Sequence[float]) -> float:
    return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at(ranked: Sequence[Hashable], rel: dict, k: int) -> float:
    gains = [rel.get(i, 0) for i in ranked[:k]]
    ideal = sorted(rel.values(), reverse=True)[:k]
    idcg = dcg(ideal)
    return dcg(gains) / idcg if idcg > 0 else 0.0


def average_precision(
    ranked: Sequence[Hashable], rel: dict, k: int = 100, threshold: int = REL
) -> float:
    n_rel = sum(1 for g in rel.values() if g >= threshold)
    if n_rel == 0:
        return 0.0
    hits, total = 0, 0.0
    for i, d in enumerate(ranked[:k], 1):
        if rel.get(d, 0) >= threshold:
            hits += 1
            total += hits / i
    return total / n_rel


def bpref(ranked: Sequence[Hashable], rel: dict, threshold: int = REL) -> float:
    """Buckley & Voorhees 2004: robust to incomplete judgements (unjudged docs ignored)."""
    R = sum(1 for g in rel.values() if g >= threshold)
    N = sum(1 for g in rel.values() if g < threshold)
    if R == 0:
        return 0.0
    denom = min(R, N) or 1
    nonrel_seen, score = 0, 0.0
    for d in ranked:
        if d not in rel:
            continue
        if rel[d] >= threshold:
            score += 1 - min(nonrel_seen, denom) / denom
        else:
            nonrel_seen += 1
    return score / R


def success_at(ranked: Sequence[Hashable], rel: dict, k: int, grade: int = 3) -> float:
    return 1.0 if any(rel.get(d, 0) >= grade for d in ranked[:k]) else 0.0


def judged_at(ranked: Sequence[Hashable], rel: dict, k: int) -> float:
    top = ranked[:k]
    return sum(1 for d in top if d in rel) / len(top) if top else 0.0


def rbo(a: Sequence[Hashable], b: Sequence[Hashable], p: float = 0.9, depth: int = 10) -> float:
    """Rank-biased overlap (Webber et al. 2010), truncated at ``depth``; 1 = identical."""
    seen_a, seen_b, score = set(), set(), 0.0
    for d in range(1, depth + 1):
        if d <= len(a):
            seen_a.add(a[d - 1])
        if d <= len(b):
            seen_b.add(b[d - 1])
        score += p ** (d - 1) * len(seen_a & seen_b) / d
    return (1 - p) * score / (1 - p**depth)


def intra_list_diversity(vectors: list[np.ndarray | None]) -> float:
    """1 - mean pairwise cosine similarity of the shown items (embedding diversity)."""
    vs = [v / (np.linalg.norm(v) + 1e-9) for v in vectors if v is not None]
    if len(vs) < 2:
        return 0.0
    m = np.stack(vs)
    sims = m @ m.T
    n = len(vs)
    return float(1 - (sims.sum() - n) / (n * (n - 1)))


def gini(counts: Sequence[float]) -> float:
    """Exposure concentration (0 = everyone equally exposed, 1 = one item gets everything)."""
    x = np.sort(np.asarray(counts, dtype=float))
    if x.sum() == 0 or len(x) < 2:
        return 0.0
    n = len(x)
    return float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum()))


def exposure_gini(lists: list[list[str]]) -> float:
    return gini(list(Counter(c for lst in lists for c in lst).values()))


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def bootstrap_ci(
    values: Sequence[float], n: int = 2000, alpha: float = 0.05, seed: int = 0
) -> tuple[float, float, float]:
    """Mean with a percentile bootstrap confidence interval over queries/personas."""
    v = np.asarray(values, dtype=float)
    if len(v) == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    boots = v[rng.integers(0, len(v), size=(n, len(v)))].mean(axis=1)
    return (
        float(v.mean()),
        float(np.quantile(boots, alpha / 2)),
        float(np.quantile(boots, 1 - alpha / 2)),
    )


def paired_randomization_test(
    a: Sequence[float], b: Sequence[float], n: int = 10000, seed: int = 0
) -> float:
    """Two-sided p-value for mean(a) != mean(b) on paired per-query scores (sign flips)."""
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    if len(d) == 0 or np.allclose(d, 0):
        return 1.0
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n, len(d)))
    null = np.abs((signs * d).mean(axis=1))
    return float((np.sum(null >= abs(d.mean())) + 1) / (n + 1))
