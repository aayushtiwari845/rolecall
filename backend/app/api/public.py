"""Public endpoints: eval results and a no-login demo feed built from a sample profile."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, rate_limit
from app.enrich.embed import embed_query
from app.models import EvalRun
from app.search.engine import ranked_to_dict, recommend
from app.search.filters import JobFilters
from app.search.rank import UserContext

router = APIRouter(prefix="/api", tags=["public"])

DEMO_PROFILES = {
    "backend_new_grad": {
        "label": "Backend new grad · Bengaluru / remote",
        "text": "Final-year computer science student. Backend internships building REST APIs in Python (FastAPI) "
        "and Java (Spring Boot), PostgreSQL, Redis, Docker, AWS. Interested in distributed systems.",
        "skills": [
            "Python",
            "FastAPI",
            "Java",
            "Spring Boot",
            "PostgreSQL",
            "Redis",
            "Docker",
            "AWS",
            "REST APIs",
            "Microservices",
            "System Design",
            "SQL",
            "Git",
        ],
        "levels": ["intern", "new_grad"],
        "families": ["backend", "swe", "fullstack"],
        "cities": ["Bengaluru", "Mumbai"],
    },
    "ml_intern": {
        "label": "ML / AI intern · India or remote",
        "text": "Student in AI and data science. Built LLM apps with RAG, embeddings and vector databases, trained "
        "PyTorch models, deployed with Docker. Looking for ML or AI engineering internships.",
        "skills": [
            "Python",
            "PyTorch",
            "Machine Learning",
            "Deep Learning",
            "LLMs",
            "RAG",
            "Embeddings",
            "Vector Databases",
            "NLP",
            "Docker",
            "SQL",
            "Pandas",
            "scikit-learn",
        ],
        "levels": ["intern", "new_grad"],
        "families": ["ml", "ai_llm", "data_science", "swe"],
        "cities": ["Bengaluru", "Mumbai", "Hyderabad", "Pune", "Gurugram"],
    },
    "data_eng_junior": {
        "label": "Data engineer · 1-2 yrs",
        "text": "Data engineer with 1.5 years building ETL pipelines in Spark and Airflow, dbt models on Snowflake, "
        "Kafka streaming, SQL and Python.",
        "skills": [
            "Python",
            "SQL",
            "Apache Spark",
            "Airflow",
            "dbt",
            "Snowflake",
            "Kafka",
            "ETL",
            "Data Warehousing",
            "AWS",
        ],
        "levels": ["new_grad", "junior", "mid"],
        "families": ["data_eng", "backend", "swe"],
        "cities": ["Bengaluru", "Pune", "Hyderabad"],
    },
}


@router.get("/demo/profiles")
def demo_profiles():
    return {
        "items": [
            {"id": k, "label": v["label"], "skills": v["skills"]} for k, v in DEMO_PROFILES.items()
        ]
    }


class DemoBody(BaseModel):
    profile: str = "backend_new_grad"
    limit: int = 12


@router.post("/demo/feed")
def demo_feed(
    body: DemoBody, db: Session = Depends(get_db), _rl=Depends(rate_limit("demo", 30, 10))
):
    p = DEMO_PROFILES.get(body.profile, DEMO_PROFILES["backend_new_grad"])
    ctx = UserContext(
        skills=set(p["skills"]),
        years=0.0 if "intern" in p["levels"] else 1.5,
        levels=p["levels"],
        families=p["families"],
        cities=p["cities"],
        qvec=embed_query(p["text"]),
        lex_terms=p["skills"][:10],
    )
    filters = JobFilters(
        seniorities=p["levels"],
        role_families=p["families"],
        cities=p["cities"],
        remote_india=True,
        remote_global=True,
    )
    items = recommend(db, ctx, filters, limit=min(body.limit, 24), cache_key=f"demo:{body.profile}")
    return {"profile": p["label"], "items": [ranked_to_dict(r) for r in items]}


@router.get("/evals")
def eval_results(db: Session = Depends(get_db)):
    """Latest run of every (suite, variant)."""
    latest = (
        select(EvalRun.suite, EvalRun.variant, func.max(EvalRun.id).label("id"))
        .group_by(EvalRun.suite, EvalRun.variant)
        .subquery()
    )
    rows = db.scalars(
        select(EvalRun)
        .join(latest, EvalRun.id == latest.c.id)
        .order_by(EvalRun.suite, EvalRun.variant)
    )
    history = db.scalars(select(EvalRun).order_by(EvalRun.created_at.desc()).limit(200))
    return {
        "latest": [
            {
                "suite": r.suite,
                "variant": r.variant,
                "metrics": r.metrics,
                "config": r.config,
                "notes": r.notes,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "history": [
            {
                "suite": r.suite,
                "variant": r.variant,
                "metrics": r.metrics,
                "created_at": r.created_at.isoformat(),
            }
            for r in history
        ],
    }
