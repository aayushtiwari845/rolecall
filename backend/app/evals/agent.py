"""Agent tool-use eval: does the agent pick the right tools and avoid inventing jobs?

Each scenario is a user message with the tools we expect to be called (any order) and
tools that must not be called. The agent runs against a throwaway eval user so the
real tracker is untouched. Checks: tool selection, no fabricated job ids, and that the
final answer references at least one real job when jobs were requested.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy.orm import Session

from app.agent.loop import JOB_REF, run_turn
from app.llm.router import get_llm
from app.models import ChatThread, Job, Preferences, User

SCENARIOS = [
    {
        "msg": "Find me backend internships in Bengaluru that use Python",
        "expect": ["search_jobs"],
        "jobs": True,
    },
    {
        "msg": "What should I apply to this week?",
        "expect_any": ["recommend_jobs", "search_jobs"],
        "jobs": True,
    },
    {
        "msg": "Show me remote ML new grad roles posted in the last 2 weeks",
        "expect_any": ["search_jobs", "recommend_jobs"],
        "jobs": True,
    },
    {
        "msg": "What jobs are open at Stripe?",
        "expect_any": ["jobs_at_company", "search_jobs"],
        "jobs": True,
    },
    {
        "msg": "Remember that I only want roles in Mumbai or remote",
        "expect_any": ["remember", "update_preferences"],
        "jobs": False,
    },
    {
        "msg": "How many applications do I have in the interview stage?",
        "expect": ["list_applications"],
        "jobs": False,
    },
    {
        "msg": "Set up an alert for data engineering internships",
        "expect": ["create_alert"],
        "jobs": False,
    },
    {
        "msg": "Hi! what can you do?",
        "forbid": ["save_job", "create_alert", "update_preferences"],
        "jobs": False,
    },
]


def _eval_user(session: Session) -> User:
    email = "eval-agent@rolecall.local"
    user = session.query(User).filter_by(email=email).one_or_none()
    if user is None:
        user = User(email=email, name="Eval Bot", onboarded=True)
        user.preferences = Preferences(
            seniorities=["intern", "new_grad"], cities=["Bengaluru", "Mumbai"]
        )
        session.add(user)
        session.commit()
    return user


def run(session: Session) -> dict[str, dict]:
    if not get_llm().available:
        return {}
    user = _eval_user(session)
    passed, tool_ok, grounded, fabricated = 0, 0, 0, 0
    details = []
    for sc in SCENARIOS:
        thread = ChatThread(user_id=user.id, title="eval")
        session.add(thread)
        session.commit()
        tools, final, error = [], "", None
        for ev in run_turn(session, user, thread, sc["msg"]):
            if ev["type"] == "tool" and ev["status"] == "running":
                tools.append(ev["name"])
            elif ev["type"] == "message":
                final = ev["content"]
            elif ev["type"] == "error":
                error = ev["message"]
        ok_tools = all(t in tools for t in sc.get("expect", []))
        if sc.get("expect_any"):
            ok_tools = ok_tools and any(t in tools for t in sc["expect_any"])
        ok_tools = ok_tools and not any(t in tools for t in sc.get("forbid", []))
        refs = JOB_REF.findall(final)
        real = [r for r in refs if session.get(Job, uuid.UUID(r)) is not None]
        fake = len(refs) - len(real)
        ok_ground = (
            (not sc["jobs"])
            or bool(real)
            or bool(re.search(r"no (matching )?(jobs|roles)", final, re.I))
        )
        tool_ok += ok_tools
        grounded += ok_ground
        fabricated += fake
        passed += ok_tools and ok_ground and fake == 0 and error is None
        details.append(
            {
                "msg": sc["msg"],
                "tools": tools,
                "ok": ok_tools and ok_ground and not fake,
                "error": error,
            }
        )
        session.delete(thread)
        session.commit()
    n = len(SCENARIOS)
    return {
        "tool_use": {
            "pass_rate": round(passed / n, 3),
            "tool_selection_acc": round(tool_ok / n, 3),
            "grounded_rate": round(grounded / n, 3),
            "fabricated_job_refs": fabricated,
            "scenarios": n,
            "details": details,
        }
    }
