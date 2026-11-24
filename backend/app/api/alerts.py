"""Saved searches that feed the daily email digest."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db
from app.models import Alert, User
from app.search.filters import JobFilters

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class AlertBody(BaseModel):
    name: str
    query: str = ""
    filters: JobFilters = JobFilters()
    enabled: bool = True


def _out(a: Alert) -> dict:
    return {
        "id": str(a.id),
        "name": a.name,
        "query": a.query,
        "filters": a.filters,
        "enabled": a.enabled,
        "last_sent_at": a.last_sent_at.isoformat() if a.last_sent_at else None,
    }


@router.get("")
def list_alerts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {
        "items": [
            _out(a)
            for a in db.scalars(
                select(Alert).where(Alert.user_id == user.id).order_by(Alert.created_at)
            )
        ]
    }


@router.post("")
def create_alert(
    body: AlertBody, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    if len(list(db.scalars(select(Alert.id).where(Alert.user_id == user.id)))) >= 10:
        raise HTTPException(400, "Up to 10 alerts per account")
    a = Alert(
        user_id=user.id,
        name=body.name[:200],
        query=body.query[:300],
        filters=body.filters.model_dump(),
        enabled=body.enabled,
    )
    db.add(a)
    db.commit()
    return _out(a)


@router.put("/{alert_id}")
def update_alert(
    alert_id: uuid.UUID,
    body: AlertBody,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    a = db.scalar(select(Alert).where(Alert.id == alert_id, Alert.user_id == user.id))
    if a is None:
        raise HTTPException(404)
    a.name, a.query, a.filters, a.enabled = (
        body.name[:200],
        body.query[:300],
        body.filters.model_dump(),
        body.enabled,
    )
    db.commit()
    return _out(a)


@router.delete("/{alert_id}")
def delete_alert(
    alert_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    a = db.scalar(select(Alert).where(Alert.id == alert_id, Alert.user_id == user.id))
    if a:
        db.delete(a)
        db.commit()
    return {"ok": True}
