"""Standard IR metrics. ``ranked`` is a list of ids; ``rel`` maps id -> graded relevance."""

from __future__ import annotations

import math
from collections.abc import Hashable, Sequence


def recall_at(ranked: Sequence[Hashable], relevant: set, k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def mrr_at(ranked: Sequence[Hashable], relevant: set, k: int) -> float:
    for i, item in enumerate(ranked[:k], 1):
        if item in relevant:
            return 1.0 / i
    return 0.0


def precision_at(ranked: Sequence[Hashable], rel: dict, k: int, threshold: int = 2) -> float:
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


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0
