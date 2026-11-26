"""Make a fictional demo account: resume PDF, preferences, onboarding done.
Saves the signed-in browser state for the recording script."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SP = Path(sys.argv[1])
WEB = "http://localhost:3000"

RESUME_HTML = """<html><body style="font-family:Georgia;font-size:12px;margin:40px;line-height:1.45">
<h1 style="margin:0">Ananya Rao</h1>
<p>Final-year B.Tech, Computer Science, graduating 2027. Bengaluru, India.</p>
<h3>Skills</h3>
<p>Python, PyTorch, scikit-learn, pandas, NumPy, SQL, PostgreSQL, FastAPI, Docker, Git, Linux,
Hugging Face Transformers, LLMs, RAG, embeddings, vector databases, REST APIs, AWS basics.</p>
<h3>Experience</h3>
<p><b>Machine Learning Intern</b>, a Bengaluru fintech startup, May to July 2026.
Built a transaction categorisation model with scikit-learn and XGBoost (F1 0.91), served
it with FastAPI and Docker, and wrote evaluation dashboards in SQL.</p>
<h3>Projects</h3>
<p><b>Campus RAG assistant</b>: retrieval-augmented chatbot over university notices using
sentence embeddings, pgvector and an open LLM; evaluated answer faithfulness on 200 questions.</p>
<p><b>Resume ranker</b>: fine-tuned a small transformer with PyTorch to match resumes to job
descriptions; hybrid BM25 and dense retrieval with reciprocal rank fusion.</p>
<p><b>Distributed key-value store</b>: course project in Go with Raft replication.</p>
<h3>Achievements</h3>
<p>Smart India Hackathon finalist. 400+ data structures and algorithms problems solved.</p>
</body></html>"""

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(base_url=WEB, extra_http_headers={"X-Rolecall": "1"})
    page = ctx.new_page()
    page.set_content(RESUME_HTML)
    pdf = SP / "demo_resume.pdf"
    page.pdf(path=str(pdf), format="A4")

    r = ctx.request.post(
        "/api/auth/dev-login", data={"email": "ananya.demo@example.com", "name": "Ananya"}
    )
    print("login", r.status)
    existing = ctx.request.get("/api/resumes").json()
    for res in existing if isinstance(existing, list) else existing.get("resumes", []):
        ctx.request.delete(f"/api/resumes/{res['id']}")
    r = ctx.request.post(
        "/api/resumes",
        multipart={
            "file": {
                "name": "resume.pdf",
                "mimeType": "application/pdf",
                "buffer": pdf.read_bytes(),
            },
            "label": "ML resume",
        },
        timeout=120_000,
    )
    print("resume", r.status, r.text()[:200])
    prefs = {
        "role_families": ["ml", "data", "backend", "swe"],
        "seniorities": ["intern", "new_grad"],
        "employment_types": ["intern", "full_time"],
        "cities": ["Bengaluru"],
        "remote_india": True,
        "remote_global": True,
        "onsite_global": False,
    }
    print("prefs", ctx.request.put("/api/preferences", data=prefs).status)
    print("onboard", ctx.request.post("/api/onboarding/complete").status)
    ctx.storage_state(path=str(SP / "demo_state.json"))
    b.close()
