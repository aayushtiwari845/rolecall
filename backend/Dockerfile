# One image for the API and the worker (different commands). Works on x86 and ARM
# (Oracle Cloud Ampere free tier).
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    MODEL_CACHE_DIR=/models

RUN pip install --no-cache-dir uv==0.12.6

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# Bake the embedding + reranker models into the image so cold starts don't download them.
RUN uv run python -c "from app.enrich.embed import embed_query, rerank; embed_query('warm'); rerank('a', ['b'])"

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
RUN useradd --create-home app && chown -R app /app /models
USER app

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
