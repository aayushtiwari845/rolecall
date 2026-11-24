"""Local embeddings and cross-encoder reranking (ONNX on CPU via fastembed, no API cost).

Model: BAAI/bge-small-en-v1.5 (384-d). Small enough for a free ARM VM, strong on
retrieval benchmarks for its size. Queries get bge's retrieval instruction prefix;
passages (jobs) are embedded as-is. Vectors are L2-normalised so cosine = dot product.
"""

from __future__ import annotations

import logging
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Job

log = logging.getLogger(__name__)

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
_lock = threading.Lock()


def _cache_dir() -> str:
    path = Path(get_settings().model_cache_dir)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


@lru_cache(maxsize=1)
def _embedder():
    from fastembed import TextEmbedding

    s = get_settings()
    log.info("loading embedding model %s", s.embedding_model)
    return TextEmbedding(model_name=s.embedding_model, cache_dir=_cache_dir())


@lru_cache(maxsize=1)
def _reranker():
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    s = get_settings()
    log.info("loading reranker %s", s.reranker_model)
    return TextCrossEncoder(model_name=s.reranker_model, cache_dir=_cache_dir())


def _normalize(vecs: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.clip(norms, 1e-12, None)


def embed_passages(texts: list[str], batch_size: int = 32) -> np.ndarray:
    if not texts:
        return np.zeros((0, get_settings().embedding_dim), dtype=np.float32)
    with _lock:
        vecs = np.array(list(_embedder().embed(texts, batch_size=batch_size)), dtype=np.float32)
    return _normalize(vecs)


def embed_query(text: str) -> np.ndarray:
    return embed_passages([QUERY_PREFIX + text])[0]


def rerank(query: str, docs: list[str]) -> list[float]:
    if not docs:
        return []
    with _lock:
        return [float(s) for s in _reranker().rerank(query, docs)]


def job_text(job: Job) -> str:
    """What we embed for a job: the parts that describe the work, title first."""
    bits = [
        job.title,
        f"at {job.company_name}",
        f"Role: {job.role_family or ''}, level: {job.seniority or ''}.",
    ]
    if job.skills:
        bits.append("Skills: " + ", ".join(job.skills[:25]) + ".")
    if job.summary:
        bits.append(job.summary)
    bits.append((job.description_text or "")[:1800])
    return "\n".join(b for b in bits if b)


def embed_pending(session: Session, batch: int = 64, max_jobs: int | None = None) -> int:
    """Embed open tech jobs whose content changed since they were last embedded."""
    done = 0
    while True:
        q = (
            select(Job)
            .where(
                Job.status == "open",
                Job.is_tech.is_(True),
                or_(Job.embedding.is_(None), Job.embedded_hash.is_distinct_from(Job.content_hash)),
            )
            .limit(batch)
        )
        jobs = list(session.scalars(q))
        if not jobs:
            break
        vecs = embed_passages([job_text(j) for j in jobs])
        for j, v in zip(jobs, vecs, strict=True):
            j.embedding = v.tolist()
            j.embedded_hash = j.content_hash
        session.commit()
        done += len(jobs)
        log.info("embedded %d jobs", done)
        if max_jobs and done >= max_jobs:
            break
    return done
