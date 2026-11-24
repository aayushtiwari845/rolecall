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
