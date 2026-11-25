"""Application tracker (kanban) with Excel / CSV export."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db
from app.models import Application, AppStatus, Interaction, Job, User
from app.search.engine import invalidate_user

router = APIRouter(prefix="/api/applications", tags=["tracker"])
STATUSES = [s.value for s in AppStatus]


def _out(a: Application) -> dict:
    j = a.job
    return {
        "id": str(a.id),
        "job_id": str(a.job_id) if a.job_id else None,
        "company": a.company,
        "title": a.title,
        "url": a.url,
        "location": a.location,
        "status": a.status,
        "notes": a.notes,
        "sort_order": a.sort_order,
        "applied_at": a.applied_at.isoformat() if a.applied_at else None,
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        "job_open": (j.status == "open") if j else None,
        "seniority": j.seniority if j else None,
        "remote_type": j.remote_type if j else None,
    }


@router.get("")
def list_apps(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Application)
        .where(Application.user_id == user.id)
        .order_by(Application.status, Application.sort_order, Application.created_at.desc())
    )
    return {"items": [_out(a) for a in rows], "statuses": STATUSES}


class AppCreate(BaseModel):
    job_id: uuid.UUID | None = None
    company: str | None = None
    title: str | None = None
    url: str | None = None
    location: str | None = None
    status: str = "saved"
    notes: str = ""


@router.post("")
def create_app(body: AppCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.status not in STATUSES:
        raise HTTPException(400, "bad status")
    job = db.get(Job, body.job_id) if body.job_id else None
    if body.job_id and job is None:
        raise HTTPException(404, "job not found")
    if job:
        existing = db.scalar(
            select(Application).where(Application.user_id == user.id, Application.job_id == job.id)
        )
        if existing:
            return _out(existing)
    if not job and not (body.company and body.title):
        raise HTTPException(400, "company and title are required for manual entries")
    top = (
        db.scalar(
            select(func.min(Application.sort_order)).where(
                Application.user_id == user.id, Application.status == body.status
            )
        )
        or 0
    )
    a = Application(
        user_id=user.id,
        job_id=job.id if job else None,
        company=(job.company_name if job else body.company or "")[:200],
        title=(job.title if job else body.title or "")[:400],
        url=job.url if job else body.url,
        location=job.location_raw if job else body.location,
        status=body.status,
        notes=body.notes,
        sort_order=top - 1,
        applied_at=datetime.now(UTC) if body.status not in ("saved",) else None,
    )
    db.add(a)
    if job:
        db.add(
            Interaction(
                user_id=user.id,
                job_id=job.id,
                type="save" if body.status == "saved" else "apply",
                surface="tracker",
            )
        )
    db.commit()
    db.refresh(a)
    invalidate_user(str(user.id))
    return _out(a)


class AppPatch(BaseModel):
    status: str | None = None
    notes: str | None = None
    sort_order: float | None = None
    title: str | None = None
    company: str | None = None
    url: str | None = None


@router.patch("/{app_id}")
def update_app(
    app_id: uuid.UUID,
    body: AppPatch,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    a = db.scalar(
        select(Application).where(Application.id == app_id, Application.user_id == user.id)
    )
    if a is None:
        raise HTTPException(404)
    if body.status:
        if body.status not in STATUSES:
            raise HTTPException(400, "bad status")
        if body.status != "saved" and a.applied_at is None:
            a.applied_at = datetime.now(UTC)
            if a.job_id:
                db.add(
                    Interaction(user_id=user.id, job_id=a.job_id, type="apply", surface="tracker")
                )
        a.status = body.status
    for field in ("notes", "sort_order", "title", "company", "url"):
        v = getattr(body, field)
        if v is not None:
            setattr(a, field, v)
    db.commit()
    db.refresh(a)
    return _out(a)


@router.delete("/{app_id}")
def delete_app(
    app_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    a = db.scalar(
        select(Application).where(Application.id == app_id, Application.user_id == user.id)
    )
    if a is not None:
        db.delete(a)
        db.commit()
        invalidate_user(str(user.id))
    return {"ok": True}


COLUMNS = ["Company", "Role", "Status", "Location", "Applied on", "Added on", "Link", "Notes"]
STATUS_FILL = {
    "saved": "E8EEF9",
    "applied": "DCEBFF",
    "oa": "FFF2CC",
    "interview": "FCE4D6",
    "offer": "D9F2D9",
    "rejected": "F4CCCC",
    "withdrawn": "EDEDED",
}


def _rows(db: Session, user: User) -> list[list]:
    apps = db.scalars(
        select(Application)
        .where(Application.user_id == user.id)
        .order_by(Application.created_at.desc())
    )
    return [
        [
            a.company,
            a.title,
            a.status,
            a.location or "",
            a.applied_at.strftime("%Y-%m-%d") if a.applied_at else "",
            a.created_at.strftime("%Y-%m-%d"),
            a.url or "",
            a.notes or "",
        ]
        for a in apps
    ]


@router.get("/export")
def export(
    format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rows = _rows(db, user)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(COLUMNS)
        w.writerows(rows)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="rolecall-applications-{stamp}.csv"'
            },
        )
    wb = Workbook()
    ws = wb.active
    ws.title = "Applications"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F2937")
        cell.alignment = Alignment(vertical="center")
    for r in rows:
        ws.append(r)
        status_cell = ws.cell(row=ws.max_row, column=3)
        status_cell.fill = PatternFill("solid", fgColor=STATUS_FILL.get(r[2], "FFFFFF"))
        link = ws.cell(row=ws.max_row, column=7)
        if r[6]:
            link.hyperlink = r[6]
            link.font = Font(color="2563EB", underline="single")
    dv = DataValidation(type="list", formula1='"' + ",".join(STATUSES) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"C2:C{max(2, ws.max_row + 200)}")
    for i, width in enumerate([22, 40, 12, 26, 12, 12, 40, 50], 1):
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:H{max(1, ws.max_row)}"

    summary = wb.create_sheet("Summary")
    summary.append(["Status", "Count"])
    for cell in summary[1]:
        cell.font = Font(bold=True)
    for s in STATUSES:
        summary.append([s, f'=COUNTIF(Applications!C:C,"{s}")'])
    summary.append(["total", f"=SUM(B2:B{len(STATUSES) + 1})"])
    summary.column_dimensions["A"].width = 14

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="rolecall-applications-{stamp}.xlsx"'
        },
    )


@router.delete("/job/{job_id}")
def delete_by_job(
    job_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    """Unsave a role from the feed without knowing its tracker id."""
    a = db.scalar(
        select(Application).where(Application.user_id == user.id, Application.job_id == job_id)
    )
    if a is not None:
        db.delete(a)
        db.add(Interaction(user_id=user.id, job_id=job_id, type="unsave", surface="feed"))
        db.commit()
        invalidate_user(str(user.id))
    return {"ok": True}
