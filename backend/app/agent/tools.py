"""Agent tools. Each tool has an OpenAI-style JSON schema and a Python implementation.

Tool outputs are compact JSON (models on free tiers have small context windows), and
every job a tool returns is registered so the final answer can render it as a card.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alert, Application, AppStatus, Job, Memory, Preferences, User
from app.search.engine import invalidate_user, ranked_to_dict, recommend, search
from app.search.filters import JobFilters
from app.search.personalize import build_context, filters_from_prefs
from app.search.rank import Weights, score_candidates
from app.search.retrieval import Candidate

LEVELS = ["intern", "new_grad", "junior", "mid", "senior", "staff_plus"]
FAMILIES = [
    "swe",
    "backend",
    "frontend",
    "fullstack",
    "mobile",
    "ml",
    "ai_llm",
    "data_eng",
    "data_science",
    "infra",
    "security",
    "qa",
    "embedded",
]
STATUSES = [s.value for s in AppStatus]


@dataclass
class ToolContext:
    session: Session
    user: User
    jobs_seen: dict[str, dict] = field(default_factory=dict)

    def register(self, items: list[dict]) -> None:
        for it in items:
            self.jobs_seen[it["id"]] = it


def _compact(job: dict) -> dict:
    return {
        "id": job["id"],
        "title": job["title"],
        "company": job["company"],
        "location": job["location"],
        "remote": job["remote_type"],
        "level": job["seniority"],
        "match": job.get("match"),
        "why": job.get("reasons", [])[:2],
        "concerns": job.get("warnings", [])[:2],
        "posted": (job.get("posted_at") or "")[:10],
    }


def _filters(args: dict, base: JobFilters | None = None) -> JobFilters:
    f = base.model_copy() if base else JobFilters()
    if args.get("seniorities"):
        f.seniorities = [s for s in args["seniorities"] if s in LEVELS]
    if args.get("role_families"):
        f.role_families = [r for r in args["role_families"] if r in FAMILIES]
    if args.get("cities"):
        f.cities = args["cities"]
        f.onsite_anywhere = False
    if "remote_only" in args and args["remote_only"]:
        f.cities, f.remote_india, f.remote_global = [], True, True
    if args.get("companies"):
        f.companies = args["companies"]
    if args.get("posted_within_days"):
        f.posted_within_days = int(args["posted_within_days"])
    if args.get("employment_types"):
        f.employment_types = args["employment_types"]
    if args.get("company_tags"):
        f.company_tags = args["company_tags"]
    return f


# ------------------------------------------------------------------ implementations
def search_jobs(ctx: ToolContext, query: str = "", limit: int = 6, **filters) -> dict:
    uctx = build_context(ctx.session, ctx.user)
    items = [
        ranked_to_dict(r)
        for r in search(
            ctx.session,
            query,
            _filters(filters),
            user=uctx,
            limit=min(int(limit), 10),
            use_rerank=bool(query),
        )
    ]
    ctx.register(items)
    return {"count": len(items), "jobs": [_compact(i) for i in items]}


def recommend_jobs(ctx: ToolContext, limit: int = 6, **filters) -> dict:
    uctx = build_context(ctx.session, ctx.user)
    base = filters_from_prefs(ctx.user.preferences, uctx)
    items = [
        ranked_to_dict(r)
        for r in recommend(ctx.session, uctx, _filters(filters, base), limit=min(int(limit), 10))
    ]
    ctx.register(items)
    return {"count": len(items), "jobs": [_compact(i) for i in items]}


def _job(ctx: ToolContext, job_id: str) -> Job | None:
    try:
        return ctx.session.get(Job, uuid.UUID(str(job_id)))
    except ValueError:
        return None


def get_job_details(ctx: ToolContext, job_id: str) -> dict:
    job = _job(ctx, job_id)
    if job is None:
        return {"error": "no job with that id"}
    uctx = build_context(ctx.session, ctx.user)
    [r] = score_candidates(
        [Candidate(job_id=job.id)],
        {job.id: job},
        uctx,
        Weights(),
    )
    d = ranked_to_dict(r)
    ctx.register([d])
    return {
        **_compact(d),
        "skills": job.skills[:15],
        "matched_skills": r.matched_skills,
        "missing_skills": r.missing_skills,
        "min_years": job.min_yoe,
        "salary": d["salary"],
        "summary": job.summary,
        "status": job.status,
        "description_excerpt": (job.description_text or "")[:1800],
        "url": job.url,
    }


def compare_jobs(ctx: ToolContext, job_ids: list[str]) -> dict:
    return {
        "jobs": [get_job_details(ctx, jid) | {"description_excerpt": None} for jid in job_ids[:4]]
    }


def save_job(ctx: ToolContext, job_id: str, status: str = "saved", notes: str = "") -> dict:
    job = _job(ctx, job_id)
    if job is None:
        return {"error": "no job with that id"}
    status = status if status in STATUSES else "saved"
    app = ctx.session.scalar(
        select(Application).where(Application.user_id == ctx.user.id, Application.job_id == job.id)
    )
    if app is None:
        app = Application(
            user_id=ctx.user.id,
            job_id=job.id,
            company=job.company_name,
            title=job.title,
            url=job.url,
            location=job.location_raw,
            status=status,
            notes=notes,
        )
        ctx.session.add(app)
    else:
        app.status = status
        if notes:
            app.notes = (app.notes + "\n" + notes).strip()
    if status != "saved" and app.applied_at is None:
        app.applied_at = datetime.now(UTC)
    ctx.session.commit()
    invalidate_user(str(ctx.user.id))
    return {"ok": True, "tracker_status": status, "job": f"{job.title} at {job.company_name}"}


def list_applications(ctx: ToolContext, status: str | None = None) -> dict:
    q = select(Application).where(Application.user_id == ctx.user.id)
    if status in STATUSES:
        q = q.where(Application.status == status)
    apps = list(ctx.session.scalars(q.order_by(Application.updated_at.desc()).limit(40)))
    return {
        "count": len(apps),
        "applications": [
            {
                "job_id": str(a.job_id) if a.job_id else None,
                "company": a.company,
                "title": a.title,
                "status": a.status,
                "applied": a.applied_at.date().isoformat() if a.applied_at else None,
                "notes": a.notes[:200],
            }
            for a in apps
        ],
    }


def create_alert(ctx: ToolContext, name: str, query: str = "", **filters) -> dict:
    f = _filters(filters)
    ctx.session.add(
        Alert(user_id=ctx.user.id, name=name[:200], query=query[:300], filters=f.model_dump())
    )
    prefs = ctx.user.preferences
    ctx.session.commit()
    note = (
        ""
        if (prefs and prefs.digest_enabled)
        else " Email digests are off; the user can enable them in Settings."
    )
    return {"ok": True, "message": f"Alert '{name}' created.{note}"}


def update_preferences(ctx: ToolContext, **changes) -> dict:
    prefs = ctx.user.preferences or Preferences(user_id=ctx.user.id)
    if ctx.user.preferences is None:
        ctx.session.add(prefs)
    applied = {}
    for key in ("cities", "seniorities", "role_families", "employment_types", "excluded_companies"):
        if key in changes and isinstance(changes[key], list):
            setattr(prefs, key, changes[key])
            applied[key] = changes[key]
    for key in ("remote_india", "remote_global"):
        if key in changes:
            setattr(prefs, key, bool(changes[key]))
            applied[key] = bool(changes[key])
    ctx.session.commit()
    invalidate_user(str(ctx.user.id))
    return {"ok": True, "updated": applied}


def remember(ctx: ToolContext, fact: str) -> dict:
    fact = fact.strip()[:300]
    if not fact:
        return {"ok": False}
    existing = [
        m.content.lower()
        for m in ctx.session.scalars(select(Memory).where(Memory.user_id == ctx.user.id))
    ]
    if fact.lower() not in existing:
        ctx.session.add(Memory(user_id=ctx.user.id, content=fact))
        ctx.session.commit()
    return {"ok": True}


def jobs_at_company(ctx: ToolContext, company: str, limit: int = 8) -> dict:
    return (
        search_jobs(ctx, query="", limit=limit, companies=[company])
        if company
        else {"error": "company required"}
    )


# ------------------------------------------------------------------ schemas
_FILTER_PROPS: dict[str, Any] = {
    "seniorities": {"type": "array", "items": {"type": "string", "enum": LEVELS}},
    "role_families": {"type": "array", "items": {"type": "string", "enum": FAMILIES}},
    "cities": {
        "type": "array",
        "items": {"type": "string"},
        "description": "e.g. Bengaluru, Mumbai, Hyderabad",
    },
    "remote_only": {"type": "boolean"},
    "companies": {"type": "array", "items": {"type": "string"}},
    "company_tags": {
        "type": "array",
        "items": {
            "type": "string",
            "enum": [
                "in",
                "ai",
                "fintech",
                "quant",
                "devtools",
                "infra",
                "data",
                "consumer",
                "saas",
            ],
        },
    },
    "posted_within_days": {"type": "integer"},
    "employment_types": {
        "type": "array",
        "items": {"type": "string", "enum": ["full_time", "intern", "contract", "part_time"]},
    },
}


def _fn(name: str, description: str, props: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": props, "required": required or []},
        },
    }


TOOL_SCHEMAS = [
    _fn(
        "search_jobs",
        "Search the live job index with a free-text query plus optional filters. Results are personalised to the user.",
        {"query": {"type": "string"}, "limit": {"type": "integer"}, **_FILTER_PROPS},
    ),
    _fn(
        "recommend_jobs",
        "Get the user's personalised recommendations (their saved preferences apply; filters narrow further).",
        {"limit": {"type": "integer"}, **_FILTER_PROPS},
    ),
    _fn(
        "get_job_details",
        "Full details of one job, including skills the user has and lacks for it.",
        {"job_id": {"type": "string"}},
        ["job_id"],
    ),
    _fn(
        "compare_jobs",
        "Compare 2-4 jobs side by side.",
        {"job_ids": {"type": "array", "items": {"type": "string"}}},
        ["job_ids"],
    ),
    _fn(
        "save_job",
        "Add a job to the user's application tracker or change its status.",
        {
            "job_id": {"type": "string"},
            "status": {"type": "string", "enum": STATUSES},
            "notes": {"type": "string"},
        },
        ["job_id"],
    ),
    _fn(
        "list_applications",
        "List the user's tracked applications, optionally by status.",
        {"status": {"type": "string", "enum": STATUSES}},
    ),
    _fn(
        "create_alert",
        "Create a saved search that emails new matching jobs.",
        {"name": {"type": "string"}, "query": {"type": "string"}, **_FILTER_PROPS},
        ["name"],
    ),
    _fn(
        "update_preferences",
        "Change the user's job preferences (only when they ask).",
        {
            "cities": {"type": "array", "items": {"type": "string"}},
            "seniorities": _FILTER_PROPS["seniorities"],
            "role_families": _FILTER_PROPS["role_families"],
            "employment_types": _FILTER_PROPS["employment_types"],
            "excluded_companies": {"type": "array", "items": {"type": "string"}},
            "remote_india": {"type": "boolean"},
            "remote_global": {"type": "boolean"},
        },
    ),
    _fn(
        "remember",
        "Store a durable fact about the user's job search (preference, constraint, goal) for future chats.",
        {"fact": {"type": "string"}},
        ["fact"],
    ),
    _fn(
        "jobs_at_company",
        "List open roles at a specific company.",
        {"company": {"type": "string"}, "limit": {"type": "integer"}},
        ["company"],
    ),
]

TOOLS: dict[str, Callable[..., dict]] = {
    "search_jobs": search_jobs,
    "recommend_jobs": recommend_jobs,
    "get_job_details": get_job_details,
    "compare_jobs": compare_jobs,
    "save_job": save_job,
    "list_applications": list_applications,
    "create_alert": create_alert,
    "update_preferences": update_preferences,
    "remember": remember,
    "jobs_at_company": jobs_at_company,
}


def run_tool(ctx: ToolContext, name: str, arguments: str | dict) -> dict:
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
    except ValueError:
        return {"error": "arguments were not valid JSON"}
    try:
        return fn(ctx, **{k: v for k, v in args.items() if v is not None})
    except TypeError as e:
        return {"error": f"bad arguments: {e}"}
    except Exception as e:  # noqa: BLE001 - report tool failure to the model instead of crashing
        ctx.session.rollback()
        return {"error": f"tool failed: {type(e).__name__}"}


def summarize_result(name: str, result: dict) -> str:
    if "error" in result:
        return f"error: {result['error']}"
    if "jobs" in result and isinstance(result["jobs"], list):
        return f"found {len(result['jobs'])} jobs"
    if name == "list_applications":
        return f"{result.get('count', 0)} applications"
    if name in ("save_job", "create_alert", "update_preferences", "remember"):
        return "done"
    return "ok"
