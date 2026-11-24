"""Chat threads with the career agent; replies stream as server-sent events."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agent.loop import run_turn
from app.api.deps import current_user, get_db, rate_limit
from app.db import SessionLocal
from app.llm.router import get_llm
from app.models import ChatMessage, ChatThread, Memory, User

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("/status")
def status():
    return {"available": get_llm().available}


@router.get("/threads")
def threads(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(ChatThread)
        .where(ChatThread.user_id == user.id)
        .order_by(ChatThread.updated_at.desc())
        .limit(50)
    )
    return {
        "items": [
            {"id": str(t.id), "title": t.title, "updated_at": t.updated_at.isoformat()}
            for t in rows
        ]
    }


@router.post("/threads")
def new_thread(user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = ChatThread(user_id=user.id)
    db.add(t)
    db.commit()
    return {"id": str(t.id), "title": t.title}


def _thread(db: Session, user: User, thread_id: uuid.UUID) -> ChatThread:
    t = db.scalar(
        select(ChatThread).where(ChatThread.id == thread_id, ChatThread.user_id == user.id)
    )
    if t is None:
        raise HTTPException(404)
    return t


@router.get("/threads/{thread_id}")
def get_thread(
    thread_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    t = _thread(db, user, thread_id)
    msgs = db.scalars(
        select(ChatMessage).where(ChatMessage.thread_id == t.id).order_by(ChatMessage.id)
    )
    out = []
    for m in msgs:
        if m.role == "user" or (m.role == "assistant" and not m.tool_calls):
            out.append(
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "jobs": (m.data or {}).get("jobs", []),
                }
            )
        elif m.role == "assistant" and m.tool_calls:
            for c in m.tool_calls:
                out.append(
                    {
                        "id": f"{m.id}-{c['id']}",
                        "role": "tool",
                        "name": c["function"]["name"],
                        "status": "done",
                    }
                )
    return {"id": str(t.id), "title": t.title, "messages": out}


@router.delete("/threads/{thread_id}")
def delete_thread(
    thread_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    db.delete(_thread(db, user, thread_id))
    db.commit()
    return {"ok": True}


class MessageBody(BaseModel):
    content: str


@router.post("/threads/{thread_id}/messages")
def send_message(
    thread_id: uuid.UUID,
    body: MessageBody,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    _rl=Depends(rate_limit("chat", 12, 6)),
):
    if not body.content.strip():
        raise HTTPException(400, "empty message")
    _thread(db, user, thread_id)
    user_id = user.id

    def events():
        # A dedicated session: the request-scoped one closes when the handler returns.
        session = SessionLocal()
        try:
            u = session.get(User, user_id)
            t = session.get(ChatThread, thread_id)
            for ev in run_turn(session, u, t, body.content):
                yield f"data: {json.dumps(ev, default=str)}\n\n"
        except Exception:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'message': 'Something went wrong.'})}\n\n"
            raise
        finally:
            session.close()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/memories")
def memories(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Memory).where(Memory.user_id == user.id).order_by(Memory.created_at))
    return {"items": [{"id": m.id, "content": m.content, "kind": m.kind} for m in rows]}


@router.delete("/memories/{memory_id}")
def forget(memory_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(delete(Memory).where(Memory.id == memory_id, Memory.user_id == user.id))
    db.commit()
    return {"ok": True}
