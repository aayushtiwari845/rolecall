"""Field-level accuracy of job understanding against hand-labelled postings.

Gold file: ``evals/data/extraction_gold.jsonl``; each line has the posting text and the
correct seniority, role family, remote type, min years and employment type, labelled
by reading the posting. Compares the rules alone with rules + LLM refinement.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.enrich import rules
from app.enrich.llm_extract import apply_extraction, extract
from app.ingest.types import RawJob
from app.llm.router import LLMError, get_llm
from app.models import Job

GOLD = Path(__file__).resolve().parents[2] / "evals" / "data" / "extraction_gold.jsonl"
FIELDS = ["seniority", "role_family", "remote_type", "employment_type", "min_yoe"]


def load_gold(path: Path = GOLD) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _predict_rules(case: dict) -> dict:
    raw = RawJob(
        source_kind=case.get("source", "gold"),
        source_job_id=case["id"],
        company_name=case["company"],
        title=case["title"],
        url="",
        description_text=case["text"],
        location_raw=case.get("location"),
        remote_hint=case.get("remote_hint"),
        employment_hint=case.get("employment_hint"),
    )
    e = rules.enrich(raw)
    return {
        "seniority": e.seniority,
        "role_family": e.role_family,
        "remote_type": e.remote_type,
        "employment_type": e.employment_type,
        "min_yoe": e.min_yoe,
        "_enrichment": e,
    }


def _predict_llm(case: dict, base: dict) -> dict | None:
    llm = get_llm()
    if not llm.available:
        return None
    e = base["_enrichment"]
    job = Job(
        title=case["title"],
        company_name=case["company"],
        location_raw=case.get("location"),
        description_text=case["text"],
        seniority=e.seniority,
        role_family=e.role_family,
        min_yoe=e.min_yoe,
        skills=list(e.skills),
    )
    try:
        apply_extraction(job, extract(llm, job))
    except (LLMError, ValueError):
        return None
    return {
        **base,
        "seniority": job.seniority,
        "role_family": job.role_family,
        "min_yoe": job.min_yoe,
    }


def _match(field: str, pred, gold) -> bool:
    if isinstance(gold, list):  # genuinely ambiguous postings accept any listed answer
        return any(_match(field, pred, g) for g in gold)
    if field == "min_yoe":
        if gold is None or pred is None:
            return gold is pred
        return abs(float(pred) - float(gold)) <= 0.5
    return pred == gold


def run(use_llm: bool = True) -> dict[str, dict]:
    gold = load_gold()
    if not gold:
        return {}
    preds: dict[str, list[dict]] = {"rules": [], "rules+llm": []}
    for case in gold:
        base = _predict_rules(case)
        preds["rules"].append(base)
        if use_llm:
            p = _predict_llm(case, base)
            if p:
                preds["rules+llm"].append(p)
    out = {}
    for name, plist in preds.items():
        if len(plist) != len(gold):
            continue
        metrics = {}
        for f in FIELDS:
            hits = [_match(f, p[f], g.get(f)) for p, g in zip(plist, gold, strict=True) if f in g]
            metrics[f"{f}_acc"] = round(sum(hits) / len(hits), 4) if hits else None
        accs = [v for v in metrics.values() if v is not None]
        metrics["macro_acc"] = round(sum(accs) / len(accs), 4) if accs else None
        metrics["cases"] = len(gold)
        out[name] = metrics
    return out
