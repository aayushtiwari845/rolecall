"""Preferences, resumes (multiple per user, e.g. one per target role), feedback and account."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db, rate_limit
from app.enrich.embed import embed_query
from app.llm.router import get_llm
from app.models import Interaction, Job, Preferences, Resume, User
from app.resume.parse import parse_resume, pdf_text, profile_text
from app.search.engine import invalidate_user

router = APIRouter(prefix="/api", tags=["profile"])

MAX_RESUME_BYTES = 5 * 1024 * 1024


class PrefsBody(BaseModel):
    role_families: list[str] = Field(default_factory=list)
    seniorities: list[str] = Field(default_factory=list)
    employment_types: list[str] = Field(default_factory=list)
    cities: list[str] = Field(default_factory=list)
    remote_india: bool = True
    remote_global: bool = True
    onsite_global: bool = False
    min_salary_inr: float | None = None
    excluded_companies: list[str] = Field(default_factory=list)
    digest_enabled: bool = False
    digest_hour_ist: int = Field(9, ge=0, le=23)


def _prefs(user: User) -> Preferences:
    if user.preferences is None:
        user.preferences = Preferences()
    return user.preferences


@router.get("/preferences")
def get_prefs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _prefs(user)
    db.commit()
    return PrefsBody(
        role_families=p.role_families or [],
        seniorities=p.seniorities or [],
        employment_types=p.employment_types or [],
        cities=p.cities or [],
        remote_india=p.remote_india,
        remote_global=p.remote_global,
        onsite_global=p.onsite_global,
        min_salary_inr=p.min_salary_inr,
        excluded_companies=p.excluded_companies or [],
        digest_enabled=p.digest_enabled,
        digest_hour_ist=p.digest_hour_ist,
    )


@router.put("/preferences")
def put_prefs(body: PrefsBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _prefs(user)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    db.commit()
    invalidate_user(str(user.id))
    return body


@router.post("/onboarding/complete")
def complete_onboarding(user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.onboarded = True
    db.commit()
    return {"ok": True}


def _resume_out(r: Resume) -> dict:
    p = r.profile or {}
    return {
        "id": str(r.id),
        "label": r.label,
        "is_default": r.is_default,
        "created_at": r.created_at.isoformat(),
        "skills": r.skills,
        "years_experience": r.years_experience,
        "parsed_by": r.parsed_by,
        "headline": p.get("headline"),
        "summary": p.get("summary"),
        "target_titles": p.get("target_titles") or [],
        "suggested_role_families": p.get("suggested_role_families") or [],
        "suggested_seniorities": p.get("suggested_seniorities") or [],
        "graduation_year": p.get("graduation_year"),
        "is_student": p.get("is_student"),
    }


@router.get("/resumes")
def list_resumes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Resume).where(Resume.user_id == user.id).order_by(Resume.created_at))
    return {"items": [_resume_out(r) for r in rows]}


@router.post("/resumes")
async def upload_resume(
    file: UploadFile = File(...),
    label: str = Form("My resume"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    _rl=Depends(rate_limit("resume", 6, 4)),
):
    data = await file.read(MAX_RESUME_BYTES + 1)
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(413, "Resume must be under 5 MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "Please upload a PDF")
    try:
        text = pdf_text(data)
    except Exception as e:  # noqa: BLE001 - malformed PDFs raise many types
        raise HTTPException(422, "Could not read that PDF") from e
    if len(text) < 200:
        raise HTTPException(422, "That PDF has very little text. Is it a scanned image?")
    profile = parse_resume(text, get_llm())
    from app.resume.parse import redact

    clean = redact(text)
    count = len(list(db.scalars(select(Resume.id).where(Resume.user_id == user.id))))
    if count >= 5:
        raise HTTPException(400, "You can keep up to 5 resumes. Delete one first.")
    r = Resume(
        user_id=user.id,
        label=label[:120] or "My resume",
        is_default=count == 0,
        text=clean,
        profile=profile,
        skills=profile["skills"],
        years_experience=profile["years_experience"],
        parsed_by=profile["parsed_by"],
        embedding=embed_query(profile_text(profile, clean)).tolist(),
    )
    db.add(r)
    db.commit()
    invalidate_user(str(user.id))
    return _resume_out(r)


class ResumePatch(BaseModel):
    label: str | None = None
    is_default: bool | None = None
    skills: list[str] | None = None


@router.patch("/resumes/{resume_id}")
def patch_resume(
    resume_id: uuid.UUID,
    body: ResumePatch,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    r = db.scalar(select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id))
    if r is None:
        raise HTTPException(404)
    if body.label:
        r.label = body.label[:120]
    if body.skills is not None:
        r.skills = body.skills[:60]
        r.profile = {**(r.profile or {}), "skills": r.skills}
        r.embedding = embed_query(profile_text(r.profile, r.text)).tolist()
    if body.is_default:
        for other in db.scalars(select(Resume).where(Resume.user_id == user.id)):
            other.is_default = other.id == r.id
    db.commit()
    invalidate_user(str(user.id))
    return _resume_out(r)


@router.delete("/resumes/{resume_id}")
def delete_resume(
    resume_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    db.execute(delete(Resume).where(Resume.id == resume_id, Resume.user_id == user.id))
    db.commit()
    invalidate_user(str(user.id))
    return {"ok": True}


FEEDBACK_TYPES = {
    "click",
    "save",
    "unsave",
    "dismiss",
    "undismiss",
    "apply",
    "more_like",
    "less_like",
    "apply_click",
}


class InteractionBody(BaseModel):
    job_id: uuid.UUID
    type: str
    surface: str | None = None
    position: int | None = None
    query: str | None = None


@router.post("/interactions")
def record_interaction(
    body: InteractionBody, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    if body.type not in FEEDBACK_TYPES:
        raise HTTPException(400, "unknown interaction type")
    if db.get(Job, body.job_id) is None:
        raise HTTPException(404)
    if body.type in ("undismiss", "unsave"):
        undo = "dismiss" if body.type == "undismiss" else "save"
        db.execute(
            delete(Interaction).where(
                Interaction.user_id == user.id,
                Interaction.job_id == body.job_id,
                Interaction.type == undo,
            )
        )
    db.add(
        Interaction(
            user_id=user.id,
            job_id=body.job_id,
            type=body.type,
            surface=body.surface,
            position=body.position,
            query=body.query,
        )
    )
    db.commit()
    if body.type not in ("click", "apply_click"):
        invalidate_user(str(user.id))
    return {"ok": True}


@router.get("/me/export")
def export_my_data(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Everything we store about you, as JSON."""
    from app.models import Alert, Application, Memory

    return {
        "user": {"email": user.email, "name": user.name, "created_at": user.created_at.isoformat()},
        "preferences": get_prefs(user, db).model_dump(),
        "resumes": [
            _resume_out(r) for r in db.scalars(select(Resume).where(Resume.user_id == user.id))
        ],
        "applications": [
            {"company": a.company, "title": a.title, "status": a.status, "notes": a.notes}
            for a in db.scalars(select(Application).where(Application.user_id == user.id))
        ],
        "alerts": [
            {"name": a.name, "query": a.query, "filters": a.filters}
            for a in db.scalars(select(Alert).where(Alert.user_id == user.id))
        ],
        "memories": [
            m.content for m in db.scalars(select(Memory).where(Memory.user_id == user.id))
        ],
    }


@router.delete("/me")
def delete_account(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Hard-delete the account and everything attached to it."""
    db.delete(user)
    db.commit()
    from fastapi.responses import JSONResponse

    from app.config import get_settings

    resp = JSONResponse({"ok": True})
    resp.delete_cookie(get_settings().session_cookie, path="/")
    return resp
