# Rolecall backend

FastAPI service, ingestion workers and the recommendation engine.

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
uv run rolecall --help     # ingestion, enrichment, evals
```

See the root README and `docs/` for the architecture.
