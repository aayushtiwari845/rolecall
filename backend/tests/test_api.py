"""End-to-end API flow against a real Postgres: sign in, upload a resume, get a ranked
feed, search, save to the tracker, export, and delete the account."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

import pytest
from openpyxl import load_workbook
from pypdf import PdfWriter
from sqlalchemy import text

from app.db import session_scope
from app.enrich.rules import enrich
from app.ingest.types import RawJob
from app.models import Job
from tests.conftest import fake_vec

pytestmark = pytest.mark.db

JOBS = [
    (
        "Acme",
        "Backend Engineer Intern",
        "Bengaluru, India",
        "Build APIs in Python, FastAPI and PostgreSQL. Docker, AWS.",
    ),
    (
        "Acme",
        "Senior Staff Engineer",
        "Bengaluru, India",
        "10+ years of experience. Java, Kubernetes, distributed systems.",
    ),
    (
        "Globex",
        "Machine Learning Engineer, New Grad",
        "Remote - India",
        "PyTorch, LLMs, RAG, embeddings and Python.",
    ),
    (
        "Initech",
        "Frontend Developer",
        "Mumbai, India",
        "React, TypeScript, Next.js and CSS. 0-1 years of experience.",
    ),
    (
        "Umbrella",
        "Data Engineer Intern",
        "Pune, India",
        "Spark, Airflow, SQL, Python and dbt pipelines.",
    ),
]


@pytest.fixture()
def seeded(client):
    with session_scope() as s:
        s.execute(text("TRUNCATE jobs, users CASCADE"))
        for i, (company, title, loc, desc) in enumerate(JOBS):
            desc = (
                desc
                + " You will join a small product team, own features end to end and ship every week."
            )
            raw = RawJob(
                "greenhouse",
                f"t:{i}",
                company,
                title,
                f"https://example.com/{i}",
                desc,
                location_raw=loc,
            )
            e = enrich(raw)
            assert e.is_tech, title
            s.add(
                Job(
                    source_kind="greenhouse",
                    source_job_id=f"t:{i}",
                    company_name=company,
                    title=title,
                    url=raw.url,
                    location_raw=loc,
                    description_text=desc,
                    content_hash=str(i),
                    dedupe_key=str(i),
                    posted_at=datetime.now(UTC) - timedelta(days=i),
                    is_tech=True,
                    seniority=e.seniority,
                    role_family=e.role_family,
                    employment_type=e.employment_type,
                    remote_type=e.remote_type,
                    cities=e.cities,
                    countries=e.countries,
                    skills=e.skills,
                    min_yoe=e.min_yoe,
                    embedding=fake_vec(f"{title} {desc}").tolist(),
                    embedded_hash=str(i),
                    enrichment_version=99,
                )
            )
    return client


def _pdf_with_text(body: str) -> bytes:
    """A real PDF whose text layer contains ``body`` (pypdf has no text writer, so we
    hand-roll a minimal content stream)."""
    lines = [ln.replace("(", "").replace(")", "") for ln in body.split("\n")]
    stream = "BT /F1 10 Tf 40 800 Td 12 TL " + " ".join(f"({ln}) Tj T*" for ln in lines) + " ET"
    w = PdfWriter()
    page = w.add_blank_page(595, 842)
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})}
    )
    cs = DecodedStreamObject()
    cs.set_data(stream.encode("latin-1"))
    page[NameObject("/Contents")] = w._add_object(cs)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


RESUME = """Asha Rao  asha@example.com  +91 98765 43210
Education
B.Tech Computer Science, Example University  Aug 2022 - Jul 2026 (expected)  CGPA 9.1
Experience
Backend Intern, Foo Labs  Jun 2025 - Aug 2025
Built REST APIs with Python and FastAPI on PostgreSQL, deployed with Docker on AWS.
Projects
Search engine with embeddings and RAG using PyTorch.
Skills: Python, FastAPI, PostgreSQL, Docker, AWS, SQL, Git, React"""


def test_full_user_flow(seeded):
    c = seeded
    assert c.get("/api/auth/me").status_code == 401
    r = c.post("/api/auth/dev-login", json={"email": "asha@example.com", "name": "Asha"})
    assert r.status_code == 200 and r.json()["onboarded"] is False

    # Resume upload: parsed, redacted, embedded
    r = c.post(
        "/api/resumes",
        files={"file": ("cv.pdf", _pdf_with_text(RESUME), "application/pdf")},
        data={"label": "SWE"},
    )
    assert r.status_code == 200, r.text
    resume = r.json()
    assert {"Python", "FastAPI", "PostgreSQL"} <= set(resume["skills"])
    assert resume["is_student"] and "intern" in resume["suggested_seniorities"]
    with session_scope() as s:
        stored = s.execute(text("select text from resumes")).scalar()
    assert "asha@example.com" not in stored and "98765" not in stored

    # Preferences + onboarding
    prefs = c.get("/api/preferences").json()
    prefs.update(
        seniorities=["intern", "new_grad"], cities=["Bengaluru", "Mumbai"], remote_india=True
    )
    assert c.put("/api/preferences", json=prefs).status_code == 200
    assert c.post("/api/onboarding/complete").status_code == 200

    # Feed: early-career roles only, the backend intern role on top, senior role filtered out
    feed = c.post("/api/feed", json={}).json()["items"]
    titles = [j["title"] for j in feed]
    assert "Senior Staff Engineer" not in titles
    assert titles[0] == "Backend Engineer Intern"
    top = feed[0]
    assert top["match"] > 50 and any("skills" in r for r in top["reasons"])

    # Search
    res = c.post("/api/search", json={"q": "react typescript frontend", "filters": {}}).json()[
        "items"
    ]
    assert res[0]["title"] == "Frontend Developer"

    # Dismiss hides it from the feed
    intern_id = top["id"]
    assert (
        c.post("/api/interactions", json={"job_id": intern_id, "type": "dismiss"}).status_code
        == 200
    )
    assert intern_id not in [j["id"] for j in c.post("/api/feed", json={}).json()["items"]]
    c.post("/api/interactions", json={"job_id": intern_id, "type": "undismiss"})

    # Tracker + export
    ml = next(j for j in feed if "Machine Learning" in j["title"])
    app = c.post("/api/applications", json={"job_id": ml["id"], "status": "saved"}).json()
    assert (
        c.patch(
            f"/api/applications/{app['id']}",
            json={"status": "interview", "notes": "Round 1 Friday"},
        ).json()["status"]
        == "interview"
    )
    c.post(
        "/api/applications",
        json={"company": "Elsewhere", "title": "SDE Intern", "status": "applied"},
    )
    xlsx = c.get("/api/applications/export?format=xlsx")
    assert xlsx.status_code == 200
    ws = load_workbook(io.BytesIO(xlsx.content))["Applications"]
    rows = [[cell.value for cell in row] for row in ws.iter_rows(min_row=2)]
    assert {r[0] for r in rows} == {"Globex", "Elsewhere"}
    assert c.get("/api/applications/export?format=csv").text.startswith("Company,Role,Status")

    # Job detail carries a personal match and similar roles
    detail = c.get(f"/api/jobs/{ml['id']}").json()
    assert detail["saved"] is True and detail["match"]["match"] > 0
    assert c.get(f"/api/jobs/{ml['id']}/similar").status_code == 200

    # Public endpoints
    assert c.get("/api/stats").json()["open_jobs"] == len(JOBS)
    assert len(c.get("/api/commentary").json()["items"]) >= 1

    # Data export and account deletion
    assert c.get("/api/me/export").json()["user"]["email"] == "asha@example.com"
    assert c.delete("/api/me").status_code == 200
    assert c.get("/api/auth/me").status_code == 401


def test_writes_without_csrf_header_are_rejected(seeded):
    c = seeded
    c.post("/api/auth/dev-login", json={"email": "csrf@example.com"})
    del c.headers["X-Rolecall"]
    assert c.post("/api/onboarding/complete").status_code == 403
    c.headers["X-Rolecall"] = "1"
    assert c.post("/api/onboarding/complete").status_code == 200


def test_agent_reports_unconfigured(seeded):
    c = seeded
    c.post("/api/auth/dev-login", json={"email": "chat@example.com"})
    assert c.get("/api/chat/status").json() == {"available": False}
    tid = c.post("/api/chat/threads").json()["id"]
    body = c.post(f"/api/chat/threads/{tid}/messages", json={"content": "hi"}).text
    assert "isn't configured" in body


def test_cold_start_user_still_gets_a_feed(seeded):
    """No resume and no history: the feed falls back to fresh roles inside the filters."""
    c = seeded
    c.post("/api/auth/dev-login", json={"email": "cold@example.com"})
    prefs = c.get("/api/preferences").json()
    prefs.update(seniorities=["intern", "new_grad"], cities=["Bengaluru"], remote_india=True)
    c.put("/api/preferences", json=prefs)
    body = c.post("/api/feed", json={}).json()
    assert body["has_profile"] is False
    assert len(body["items"]) >= 1


def test_narrow_preferences_are_relaxed_and_labelled(seeded):
    c = seeded
    c.post("/api/auth/dev-login", json={"email": "narrow@example.com"})
    prefs = c.get("/api/preferences").json()
    # Nothing matches Kolkata; the feed widens to India/remote and says so on those rows.
    prefs.update(
        seniorities=["intern", "new_grad"],
        cities=["Kolkata"],
        remote_india=False,
        remote_global=False,
    )
    c.put("/api/preferences", json=prefs)
    items = c.post("/api/feed", json={}).json()["items"]
    assert items, "relaxation should find something"
    assert all(
        any(w.startswith("Outside your preferences") for w in it["warnings"]) for it in items
    )
