"""The agent loop: plan -> call tools -> observe -> answer, streamed as events.

Context the model sees each turn:
- a system prompt with today's date, the user's profile, preferences and memories
- a running summary of older turns (keeps free-tier context windows small)
- the most recent messages, including earlier tool calls and results
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.tools import TOOL_SCHEMAS, ToolContext, run_tool, summarize_result
from app.config import get_settings
from app.llm.router import LLMError, LLMRouter, get_llm
from app.models import ChatMessage, ChatThread, Memory, Resume, User

log = logging.getLogger(__name__)

MAX_STEPS = 6
HISTORY_MESSAGES = 16
SUMMARIZE_AFTER = 30
JOB_REF = re.compile(r"\[\[job:([0-9a-f-]{36})\]\]")
MEMORY_CUE = re.compile(
    r"\b(i (?:prefer|want|like|love|hate|don'?t|do not|am looking|only|can'?t|won'?t|need)|"
    r"remember|my (?:goal|target|preference)|i'?m (?:graduating|a |an |in |open|not))",
    re.I,
)

SYSTEM = """You are Rolecall, a sharp, friendly job-search agent for students and early-career engineers.
Today is {today}. You have live tools over an index of fresh tech jobs and the user's application tracker.

How to work:
- Use tools for anything about jobs. Never invent jobs, companies, salaries or links.
- Prefer recommend_jobs for "what should I apply to"; search_jobs for specific asks.
- When you mention a job, put [[job:<id>]] on its own line where a job card should appear.
- Be concise and concrete: say why a role fits and any red flags (experience asked, location).
- Only change the tracker, alerts or preferences when the user asks. Confirm what you changed.
- If the user states a lasting preference or constraint, call remember.
- You cannot apply on the user's behalf or contact recruiters.

About the user:
{profile}
Preferences: {prefs}
Things you remember: {memories}
{summary}"""


def _profile_block(session: Session, user: User) -> str:
    r = session.scalar(
        select(Resume)
        .where(Resume.user_id == user.id)
        .order_by(Resume.is_default.desc(), Resume.created_at.desc())
    )
    if r is None:
        return f"{user.name or 'User'}; no resume uploaded yet (suggest uploading one for better matches)."
    p = r.profile or {}
    return (
        f"{user.name or 'User'}. {p.get('headline') or ''}. {p.get('summary') or ''} "
        f"Years of full-time experience: {r.years_experience:g}. Graduation year: {p.get('graduation_year') or 'n/a'}. "
        f"Skills: {', '.join((r.skills or [])[:25])}."
    )


def _prefs_block(user: User) -> str:
    p = user.preferences
    if p is None:
        return "not set"
    bits = {
        "levels": p.seniorities,
        "roles": p.role_families,
        "cities": p.cities,
        "remote_india": p.remote_india,
        "remote_global": p.remote_global,
        "excluded_companies": p.excluded_companies,
    }
    return json.dumps({k: v for k, v in bits.items() if v not in (None, [], "")})


def build_messages(session: Session, user: User, thread: ChatThread) -> list[dict]:
    memories = [
        m.content
        for m in session.scalars(
            select(Memory).where(Memory.user_id == user.id).order_by(Memory.created_at).limit(30)
        )
    ]
    system = SYSTEM.format(
        today=datetime.now(UTC).strftime("%A %d %B %Y"),
        profile=_profile_block(session, user),
        prefs=_prefs_block(user),
        memories="; ".join(memories) or "nothing yet",
        summary=f"Summary of earlier conversation: {thread.summary}" if thread.summary else "",
    )
    rows = list(
        session.scalars(
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread.id)
            .order_by(ChatMessage.id.desc())
            .limit(HISTORY_MESSAGES)
        )
    )[::-1]
    # Never start the window on a dangling tool result.
    while rows and rows[0].role == "tool":
        rows.pop(0)
    msgs: list[dict] = [{"role": "system", "content": system}]
    for m in rows:
        if m.role == "tool":
            msgs.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        elif m.role == "assistant" and m.tool_calls:
            msgs.append(
                {"role": "assistant", "content": m.content or "", "tool_calls": m.tool_calls}
            )
        else:
            msgs.append({"role": m.role, "content": m.content})
    return msgs


def messages_today(session: Session, user: User) -> int:
    since = datetime.now(UTC) - timedelta(days=1)
    return (
        session.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .join(ChatThread, ChatThread.id == ChatMessage.thread_id)
            .where(
                ChatThread.user_id == user.id,
                ChatMessage.role == "user",
                ChatMessage.created_at >= since,
            )
        )
        or 0
    )


class Facts(BaseModel):
    facts: list[str]


def extract_memories(llm: LLMRouter, session: Session, user: User, text: str) -> None:
    if not MEMORY_CUE.search(text):
        return
    try:
        res = llm.structured(
            [
                {
                    "role": "user",
                    "content": (
                        "From this message by a job seeker, list durable facts about their job search worth remembering "
                        "(preferences, constraints, goals, timelines). Ignore one-off requests. Return [] if none.\n\n"
                        + text[:1500]
                    ),
                }
            ],
            Facts,
            tier="fast",
            purpose="memory",
            cache=False,
        )
    except (LLMError, ValueError):
        return
    existing = {
        m.content.lower() for m in session.scalars(select(Memory).where(Memory.user_id == user.id))
    }
    for f in res.facts[:3]:
        f = f.strip()[:300]
        if f and f.lower() not in existing:
            session.add(Memory(user_id=user.id, content=f, kind="auto"))
    session.commit()


def maybe_summarize(llm: LLMRouter, session: Session, thread: ChatThread) -> None:
    total = (
        session.scalar(
            select(func.count()).select_from(ChatMessage).where(ChatMessage.thread_id == thread.id)
        )
        or 0
    )
    if total < SUMMARIZE_AFTER or total % 10:
        return
    old = list(
        session.scalars(
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread.id, ChatMessage.role.in_(["user", "assistant"]))
            .order_by(ChatMessage.id)
            .limit(total - HISTORY_MESSAGES)
        )
    )
    transcript = "\n".join(f"{m.role}: {m.content[:400]}" for m in old if m.content)
    try:
        res = llm.chat(
            [
                {
                    "role": "user",
                    "content": "Summarise this job-search conversation in under 120 words, keeping "
                    "decisions, jobs discussed and preferences:\n\n" + transcript[:8000],
                }
            ],
            tier="fast",
            purpose="summary",
        )
        thread.summary = res.content.strip()[:1500]
        session.commit()
    except LLMError:
        pass


def run_turn(
    session: Session, user: User, thread: ChatThread, text: str, llm: LLMRouter | None = None
) -> Iterator[dict]:
    """Run one user turn, yielding UI events. Persists every message."""
    llm = llm or get_llm()
    if not llm.available:
        yield {
            "type": "error",
            "message": "The assistant isn't configured on this server yet (no LLM keys).",
        }
        return
    if messages_today(session, user) >= get_settings().agent_daily_messages_per_user:
        yield {
            "type": "error",
            "message": "You've hit today's assistant limit. It resets in 24 hours.",
        }
        return

    session.add(ChatMessage(thread_id=thread.id, role="user", content=text[:4000]))
    if thread.title == "New chat":
        thread.title = text.strip().split("\n")[0][:80] or "New chat"
    session.commit()

    ctx = ToolContext(session=session, user=user)
    messages = build_messages(session, user, thread)
    final = ""
    for step in range(MAX_STEPS):
        yield {"type": "thinking", "step": step}
        try:
            res = llm.chat(
                messages,
                tier="smart",
                tools=TOOL_SCHEMAS,
                temperature=0.3,
                purpose="agent",
                max_tokens=1400,
            )
        except LLMError as e:
            log.warning("agent LLM failure: %s", e)
            yield {
                "type": "error",
                "message": "All AI providers are busy right now. Try again in a minute.",
            }
            return
        if not res.tool_calls:
            final = res.content.strip()
            break
        messages.append(res.message())
        session.add(
            ChatMessage(
                thread_id=thread.id,
                role="assistant",
                content=res.content or "",
                tool_calls=res.tool_calls,
            )
        )
        for call in res.tool_calls:
            name = call["function"]["name"]
            args = call["function"]["arguments"]
            yield {
                "type": "tool",
                "id": call["id"],
                "name": name,
                "args": _safe_args(args),
                "status": "running",
            }
            result = run_tool(ctx, name, args)
            payload = json.dumps(result, default=str)[:6000]
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": payload})
            session.add(
                ChatMessage(
                    thread_id=thread.id,
                    role="tool",
                    tool_call_id=call["id"],
                    name=name,
                    content=payload,
                )
            )
            yield {
                "type": "tool",
                "id": call["id"],
                "name": name,
                "status": "done",
                "summary": summarize_result(name, result),
            }
        session.commit()
    else:
        final = final or "I couldn't finish that in time. Could you narrow the request?"

    refs = list(dict.fromkeys(JOB_REF.findall(final)))
    jobs = [ctx.jobs_seen[i] for i in refs if i in ctx.jobs_seen]
    if not refs and ctx.jobs_seen:
        jobs = list(ctx.jobs_seen.values())[:6]
    msg = ChatMessage(thread_id=thread.id, role="assistant", content=final, data={"jobs": jobs})
    session.add(msg)
    session.commit()
    yield {"type": "message", "content": final, "jobs": jobs, "id": msg.id}

    extract_memories(llm, session, user, text)
    maybe_summarize(llm, session, thread)
    yield {"type": "done", "thread_id": str(thread.id)}


def _safe_args(args: str | dict) -> dict:
    try:
        return json.loads(args) if isinstance(args, str) else dict(args)
    except ValueError:
        return {}
