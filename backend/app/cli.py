"""Command line entry points: ``uv run rolecall <command>``."""

from __future__ import annotations

import asyncio
import json
import logging

import typer

app = typer.Typer(
    help="Rolecall: ingestion, enrichment, embeddings and evals.", no_args_is_help=True
)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    _setup_logging(verbose)


@app.command()
def discover(limit: int = typer.Option(0, help="Only probe the first N candidates")) -> None:
    """Probe candidate companies for live ATS boards and write seeds/companies.yaml."""
    from app.ingest.discovery import discover as run
    from app.ingest.discovery import load_candidates, write_seeds

    candidates = load_candidates()
    if limit:
        candidates = candidates[:limit]
    results = asyncio.run(run(candidates))
    path = write_seeds(results)
    hits = sum(1 for r in results if r["sources"])
    typer.echo(f"{hits}/{len(results)} companies have live boards -> {path}")


@app.command()
def seed() -> None:
    """Load seeds/companies.yaml into the database."""
    from app.db import session_scope
    from app.ingest.pipeline import seed_sources

    with session_scope() as s:
        n = seed_sources(s)
    typer.echo(f"added {n} sources")


@app.command()
def ingest(
    kind: list[str] = typer.Option(None, "--kind", "-k", help="Only these source kinds"),
    limit: int = typer.Option(0, help="Max sources this run"),
    stale_hours: float = typer.Option(0, help="Skip sources crawled within this many hours"),
) -> None:
    """Crawl sources and upsert jobs."""
    from app.ingest.pipeline import ingest as run

    stats = run(kinds=kind or None, limit=limit or None, stale_hours=stale_hours or None)
    typer.echo(json.dumps(stats, indent=2))


@app.command()
def reenrich(
    all_jobs: bool = typer.Option(False, "--all", help="Also re-check closed jobs"),
) -> None:
    """Re-run the enrichment rules over stored jobs (after a rules change), in batches."""
    from sqlalchemy import select
    from sqlalchemy.orm import defer

    from app.db import session_scope
    from app.enrich.rules import RULES_VERSION, enrich
    from app.ingest.types import RawJob
    from app.models import Job

    changed = dropped = 0
    while True:
        with session_scope() as s:
            q = (
                select(Job)
                .options(defer(Job.embedding))
                .where(Job.enrichment_version < RULES_VERSION)
            )
            if not all_jobs:
                q = q.where(Job.status == "open")
            batch = list(s.scalars(q.limit(500)))
            if not batch:
                break
            for j in batch:
                e = enrich(
                    RawJob(
                        source_kind=j.source_kind,
                        source_job_id=j.source_job_id,
                        company_name=j.company_name,
                        title=j.title,
                        url=j.url,
                        description_text=j.description_text,
                        location_raw=j.location_raw,
                        department=j.department,
                        salary_min=j.salary_min,
                        salary_max=j.salary_max,
                        salary_currency=j.salary_currency,
                        salary_period=j.salary_period,
                    )
                )
                if not e.is_tech:
                    dropped += j.is_tech
                    j.is_tech = False
                else:
                    j.seniority, j.role_family, j.employment_type = (
                        e.seniority,
                        e.role_family,
                        e.employment_type,
                    )
                    j.remote_type, j.cities, j.countries = e.remote_type, e.cities, e.countries
                    j.skills, j.min_yoe, j.max_yoe = e.skills, e.min_yoe, e.max_yoe
                j.enrichment_version = RULES_VERSION
                changed += 1
        typer.echo(f"  {changed} done")
    typer.echo(f"re-enriched {changed} jobs, {dropped} no longer count as tech roles")


@app.command()
def embed(max_jobs: int = typer.Option(0, help="Stop after N jobs")) -> None:
    """Embed open jobs whose content changed."""
    from app.db import session_scope
    from app.enrich.embed import embed_pending

    with session_scope() as s:
        n = embed_pending(s, max_jobs=max_jobs or None)
    typer.echo(f"embedded {n} jobs")


@app.command("enrich-llm")
def enrich_llm(
    limit: int = typer.Option(50, help="Max jobs this run (also capped by the daily budget)"),
) -> None:
    """Refine job fields with an LLM (needs at least one provider key)."""
    from app.db import session_scope
    from app.enrich.llm_extract import enrich_pending

    with session_scope() as s:
        n = enrich_pending(s, limit=limit)
    typer.echo(f"LLM-enriched {n} jobs")


@app.command("eval")
def run_eval(
    suite: str = typer.Argument(..., help="retrieval | recommendation | extraction | agent | all"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Use template queries / rule judge only"),
) -> None:
    """Run offline evaluations and store the results."""
    from app.evals.run import run_suite

    suites = (
        ["extraction", "retrieval", "recsys", "recommendation", "agent"]
        if suite == "all"
        else [suite]
    )
    for name in suites:
        res = run_suite(name, use_llm=not no_llm)
        typer.echo(f"\n== {name} ==")
        for variant, metrics in res.items():
            shown = {k: v for k, v in metrics.items() if k != "details"}
            typer.echo(f"{variant:24s} {json.dumps(shown)}")


@app.command()
def pool(
    out: str = typer.Option("../data/pool.txt", help="Labelling sheet to write"),
    depth: int = typer.Option(10),
    with_tuned: bool = typer.Option(False, help="Also pool the tuned configuration's top results"),
    config_file: list[str] = typer.Option(
        [], help="Also pool configs from these JSON files (a 'config' key, e.g. a tuning report)"
    ),
) -> None:
    """Pool unjudged (persona, role) pairs from many ranking variants for judging."""
    from pathlib import Path

    from app.db import session_scope
    from app.evals.judged import load_personas
    from app.evals.judged import pool as run_pool
    from app.search.rank import Weights, load_config

    with session_scope() as s:
        personas = load_personas()
        extra = {"tuned": load_config()} if with_tuned else {}
        for i, f in enumerate(config_file):
            data = json.loads(Path(f).read_text(encoding="utf-8"))
            configs = data.get("top_configs") or [data.get("config", data)]
            for j, c in enumerate(configs):
                extra[f"file{i}_{j}"] = Weights.from_dict(c)
        pooled = run_pool(s, personas, extra=extra, depth=depth)
    lines, index = [], {}
    for p in personas:
        lines.append(
            f"\n### {p.id} | {p.text} | levels={p.levels} | cities={p.cities} | years={p.years}"
        )
        for i, (_jid, summ) in enumerate(pooled[p.id]):
            lines.append(f"{i}. {summ}")
        index[p.id] = [jid for jid, _ in pooled[p.id]]
    Path(out).write_text("\n".join(lines), encoding="utf-8")
    Path(out).with_suffix(".json").write_text(json.dumps(index), encoding="utf-8")
    typer.echo(f"{sum(len(v) for v in index.values())} unjudged pairs -> {out}")


@app.command("judge-add")
def judge_add(
    grades: str = typer.Argument(
        ..., help="JSON file: {persona_id: [grade per pooled item, in sheet order]}"
    ),
    index: str = typer.Option("../data/pool.json", help="Pool index written by `rolecall pool`"),
) -> None:
    """Import graded judgements (0-3) for a pooled sheet."""
    from pathlib import Path

    from app.evals.judged import add_qrels

    idx = json.loads(Path(index).read_text(encoding="utf-8"))
    g = json.loads(Path(grades).read_text(encoding="utf-8"))
    rows = []
    for pid, values in g.items():
        jobs = idx[pid]
        if len(values) != len(jobs):
            raise typer.BadParameter(f"{pid}: {len(values)} grades for {len(jobs)} pooled roles")
        rows += [
            {"persona": pid, "job": j, "grade": int(v)} for j, v in zip(jobs, values, strict=True)
        ]
    typer.echo(f"added {add_qrels(rows)} judgements")


@app.command("eval-recsys")
def eval_recsys(
    split: str = typer.Option("test", help="dev | test | all"),
    config: str = typer.Option("current", help="current (tuned if present) | default"),
) -> None:
    """Rigorous feed evaluation on judged personas (CIs, segments, constraints, stability)."""
    from app.db import session_scope
    from app.evals.judged import load_personas
    from app.evals.recsys import Evaluator
    from app.search.rank import Weights, load_config

    w = Weights() if config == "default" else load_config()
    with session_scope() as s:
        ev = Evaluator(s, load_personas(None if split == "all" else split))
        res = ev.evaluate(w, latency=True)
    for m, v in res.summary.items():
        typer.echo(f"{m:18s} {v['mean']:.4f}  [{v['lo']:.4f}, {v['hi']:.4f}]")
    typer.echo("\nsegments:")
    for g, v in res.segments.items():
        typer.echo(f"  {g:14s} {json.dumps(v)}")


@app.command()
def tune(
    trials: int = typer.Option(300),
    seed: int = typer.Option(7),
    dry_run: bool = typer.Option(False, help="Report only; do not write tuned_config.json"),
) -> None:
    """Two-stage hyperparameter optimisation on dev personas, validated on test."""
    from pathlib import Path

    from app.db import session_scope
    from app.evals.tune import run

    with session_scope() as s:
        report = run(s, trials=trials, seed=seed, write=not dry_run)
    out = Path(__file__).resolve().parents[1] / "evals" / "results" / "tuning.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    typer.echo(
        json.dumps(
            {k: report[k] for k in ("best_objective_dev", "shipped", "param_importance")}, indent=2
        )
    )
    typer.echo(json.dumps(report["test"]["compare"], indent=2))


@app.command("train-ranker")
def train_ranker() -> None:
    """Fit ranker weights from logged impressions vs clicks/saves (needs real usage)."""
    from app.db import session_scope
    from app.search.ltr import train

    with session_scope() as s:
        typer.echo(json.dumps(train(s), indent=2))


@app.command("eval-report")
def eval_report() -> None:
    """Render the latest eval results (evals/results/*.json) into docs/evals.md."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    results = root / "backend" / "evals" / "results"
    intro = {
        "extraction": "Field accuracy on 30 hand-labelled real postings (ambiguous cases accept either answer). "
        "Note: the work-mode rule was improved after looking at this set's misses, so treat it as a dev set.",
        "retrieval": "Known-item search over the live index: queries written for a stratified sample of roles; "
        "the role (or a duplicate of it) should come back near the top.",
        "recommendation": "Persona feeds; each variant's top 10 pooled and judged once on a 0-3 scale. "
        "Ablations remove one ranking component at a time.",
        "agent": "Scripted conversations checking tool choice and that answers only cite real roles.",
    }
    lines = [
        "# Evaluation results",
        "",
        "Generated by `rolecall eval-report` from `backend/evals/results/`.",
        "",
    ]
    for suite in ("extraction", "retrieval", "recommendation", "agent"):
        f = results / f"{suite}.json"
        if not f.exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        res = data["results"]
        if not res:
            continue
        cols = [k for k in next(iter(res.values())) if k != "details"]
        lines += [
            f"## {suite.title()}",
            "",
            intro[suite],
            "",
            f"Run {data['run_at'][:16].replace('T', ' ')} UTC at commit `{data.get('git_sha')}`.",
            "",
            "| variant | " + " | ".join(cols) + " |",
            "|---" * (len(cols) + 1) + "|",
        ]
        for variant, m in res.items():
            lines.append(f"| {variant} | " + " | ".join(str(m.get(c, "")) for c in cols) + " |")
        lines.append("")
    out = root / "docs" / "evals.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    typer.echo(f"wrote {out}")


@app.command()
def digest(email: str = typer.Option("", help="Send now to this user only")) -> None:
    """Send due email digests (or one user's digest immediately)."""
    from sqlalchemy import select

    from app.alerts.digest import run_digests
    from app.db import session_scope
    from app.models import User

    with session_scope() as s:
        uid = s.scalar(select(User.id).where(User.email == email.lower())) if email else None
        typer.echo(f"sent {run_digests(s, force_user_id=uid)} digests")


@app.command()
def stats() -> None:
    """Print index statistics."""
    from sqlalchemy import func, select

    from app.db import session_scope
    from app.models import CompanySource, Job

    with session_scope() as s:
        open_q = select(func.count()).select_from(Job).where(Job.status == "open", Job.is_tech)
        typer.echo(f"open tech jobs: {s.scalar(open_q)}")
        typer.echo(f"embedded: {s.scalar(open_q.where(Job.embedding.is_not(None)))}")
        for col in (Job.source_kind, Job.seniority, Job.role_family, Job.remote_type):
            rows = s.execute(
                select(col, func.count())
                .where(Job.status == "open", Job.is_tech)
                .group_by(col)
                .order_by(func.count().desc())
            ).all()
            typer.echo(f"{col.key}: " + ", ".join(f"{k}={v}" for k, v in rows))
        rows = s.execute(
            select(CompanySource.last_status, func.count()).group_by(CompanySource.last_status)
        ).all()
        typer.echo("sources: " + ", ".join(f"{k}={v}" for k, v in rows))


if __name__ == "__main__":
    app()
