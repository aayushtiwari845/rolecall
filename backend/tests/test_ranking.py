"""Properties the ranker must keep whatever its weights are tuned to."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from app.models import Job
from app.search.rank import (
    UserContext,
    Weights,
    calibrate_similarity,
    diversify,
    level_fit,
    mmr,
    score_candidates,
    skill_match,
)
from app.search.retrieval import Candidate, fuse


def _vec(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=384).astype(np.float32)
    return v / np.linalg.norm(v)


def _job(
    skills=(),
    level="new_grad",
    fam="backend",
    cities=("Bengaluru",),
    yoe=None,
    days=1,
    company="Acme",
    seed=1,
):
    return Job(
        id=uuid.uuid4(),
        title="Engineer",
        company_name=company,
        skills=list(skills),
        seniority=level,
        role_family=fam,
        cities=list(cities),
        countries=["IN"],
        remote_type="onsite",
        min_yoe=yoe,
        posted_at=datetime.now(UTC) - timedelta(days=days),
        embedding=_vec(seed).tolist(),
    )


USER = UserContext(
    skills={"Python", "FastAPI", "PostgreSQL", "Docker", "AWS"},
    years=0,
    levels=["intern", "new_grad"],
    families=["backend"],
    cities=["Bengaluru"],
    qvec=_vec(1),
)


def _score(job: Job, w: Weights | None = None, user: UserContext = USER) -> float:
    [r] = score_candidates(
        [Candidate(job_id=job.id, dense_rank=1)], {job.id: job}, user, w or Weights()
    )
    return r.score


def test_more_matched_skills_never_lowers_score():
    base = _job(skills=["Python", "Kafka", "Go", "Rust"])
    more = _job(skills=["Python", "FastAPI", "PostgreSQL", "Rust"])
    assert _score(more) > _score(base)


def test_experience_penalty_is_monotone():
    scores = [_score(_job(yoe=y)) for y in (None, 1, 2, 4, 8)]
    assert all(a >= b - 1e-6 for a, b in zip(scores, scores[1:], strict=False))
    assert scores[2] < scores[1] - 0.05  # a real penalty once beyond the slack
    assert scores[-1] > 0  # floored, never zeroed


def test_level_fit_prefers_closer_levels():
    t = ["new_grad"]
    assert (
        level_fit("new_grad", t)
        > level_fit("junior", t)
        > level_fit("mid", t)
        > level_fit("senior", t)
    )


def test_fresher_role_wins_a_tie():
    assert _score(_job(days=1)) > _score(_job(days=60))


def test_scores_are_bounded_and_deterministic():
    jobs = [_job(skills=["Python"], seed=i, days=i) for i in range(1, 30)]
    cands = [Candidate(job_id=j.id, dense_rank=1) for j in jobs]
    lookup = {j.id: j for j in jobs}
    a = score_candidates(cands, lookup, USER, Weights())
    b = score_candidates(list(reversed(cands)), lookup, USER, Weights())
    assert [r.job.id for r in a] == [r.job.id for r in b]
    assert all(0 <= r.score <= 1 and 0 <= r.match <= 100 for r in a)


@pytest.mark.parametrize(
    "cos,expected", [(0.2, 0.0), (0.5, 0.0), (0.675, 0.5), (0.85, 1.0), (0.99, 1.0)]
)
def test_similarity_calibration(cos, expected):
    assert calibrate_similarity(cos) == pytest.approx(expected)


def test_skill_saturation():
    s, matched, missing = skill_match(
        ["Python", "FastAPI", "Go"], {"Python", "FastAPI"}, saturation=6
    )
    assert s == pytest.approx(2 / 3) and missing == ["Go"]
    full, _, _ = skill_match(
        [f"S{i}" for i in range(20)] + ["Python"], {"Python"} | {f"S{i}" for i in range(5)}, 6
    )
    assert full == 1.0


def test_company_cap_and_mmr_keep_every_item():
    jobs = [_job(company="Big" if i < 8 else f"C{i}", seed=i) for i in range(12)]
    ranked = score_candidates(
        [Candidate(job_id=j.id, dense_rank=1) for j in jobs],
        {j.id: j for j in jobs},
        USER,
        Weights(),
    )
    capped = diversify(ranked, max_per_company=2, window=6)
    assert sorted(r.job.id for r in capped) == sorted(r.job.id for r in ranked)
    assert sum(r.job.company_name == "Big" for r in capped[:6]) <= 2
    assert len(mmr(ranked, 0.7)) == len(ranked)


def test_rrf_rewards_agreement_between_retrievers():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fused = fuse([(a, 0.9), (b, 0.8)], [(b, 3.0), (c, 2.0)])
    assert fused[0].job_id == b  # found by both


def test_config_roundtrip_ignores_unknown_keys():
    w = Weights.from_dict({"skills": 0.5, "not_a_field": 1})
    assert w.skills == 0.5 and Weights.from_dict(w.to_dict()) == w
