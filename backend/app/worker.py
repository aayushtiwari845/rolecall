"""Background worker: keeps the index fresh and sends digests.

Schedule (UTC):
- crawl sources not refreshed in the last 5h ............ every 2h
- embed new/changed jobs ................................ every 10 min
- LLM refinement within the daily free-tier budget ...... every 30 min
- email digests (each user picks an IST hour) ........... hourly
- retrieval evals ....................................... daily
- prune closed roles, old logs and caches ............... daily
- health check, emailing admins if crawling stalled ..... daily
- discover new and moved company boards ................. weekly

Each job takes a Postgres advisory lock, so running two workers is safe.
"""

from __future__ import annotations

import logging
import zlib
from collections.abc import Callable
from functools import wraps

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import text

from app.db import get_engine, session_scope

log = logging.getLogger("rolecall.worker")


def locked(name: str) -> Callable:
    key = zlib.crc32(name.encode())

    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        def run(*a, **kw):
            with get_engine().connect() as conn:
                got = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
                if not got:
                    log.info("%s already running elsewhere; skipping", name)
                    return None
                try:
                    log.info("starting %s", name)
                    result = fn(*a, **kw)
                    log.info("finished %s: %s", name, result)
                    return result
                except Exception:
                    log.exception("%s failed", name)
                finally:
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})

        return run

    return deco


@locked("ingest")
def job_ingest():
    from app.ingest.pipeline import ingest

    return ingest(stale_hours=5)


@locked("embed")
def job_embed():
    from app.enrich.embed import embed_pending

    with session_scope() as s:
        return embed_pending(s)


@locked("enrich_llm")
def job_enrich():
    from app.enrich.llm_extract import enrich_pending

    with session_scope() as s:
        return enrich_pending(s, limit=40)


@locked("digests")
def job_digests():
    from app.alerts.digest import run_digests

    with session_scope() as s:
        return run_digests(s)


@locked("evals")
def job_evals():
    from app.evals.run import run_suite

    return run_suite("retrieval")


@locked("prune")
def job_prune():
    from app.ingest.maintenance import prune

    with session_scope() as s:
        return prune(s)


@locked("discover")
def job_discover():
    from app.ingest.maintenance import rediscover

    with session_scope() as s:
        return rediscover(s)


@locked("health")
def job_health():
    """Email the admins when crawling has quietly stopped working."""
    from app.alerts.digest import mail_configured, send_email
    from app.config import get_settings
    from app.ingest.maintenance import health

    with session_scope() as s:
        report = health(s)
    if report["ok"]:
        return report
    log.warning("index unhealthy: %s", report)
    admins = get_settings().admin_emails
    if mail_configured() and admins:
        body = "\n".join(f"{k}: {v}" for k, v in report.items())
        for to in admins:
            send_email(to, "Rolecall: index needs attention", f"<pre>{body}</pre>", body)
    return report


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    from app.db import session_scope as _scope
    from app.ingest.pipeline import seed_sources

    with _scope() as s:
        seed_sources(s)

    sched = BlockingScheduler(
        timezone="UTC",
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 600},
    )
    sched.add_job(job_ingest, "interval", hours=2, id="ingest", next_run_time=_soon(5))
    sched.add_job(job_embed, "interval", minutes=10, id="embed", next_run_time=_soon(60))
    sched.add_job(job_enrich, "interval", minutes=30, id="enrich", next_run_time=_soon(120))
    sched.add_job(job_digests, "cron", minute=5, id="digests")
    sched.add_job(job_evals, "cron", hour=21, minute=30, id="evals")  # 03:00 IST
    sched.add_job(job_prune, "cron", hour=22, minute=15, id="prune")  # 03:45 IST
    sched.add_job(job_health, "cron", hour=3, minute=0, id="health")  # 08:30 IST
    sched.add_job(job_discover, "cron", day_of_week="sun", hour=20, id="discover")
    log.info("worker started")
    sched.start()


def _soon(seconds: int):
    from datetime import UTC, datetime, timedelta

    return datetime.now(UTC) + timedelta(seconds=seconds)


if __name__ == "__main__":
    main()
