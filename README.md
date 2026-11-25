# Rolecall

**Fresh tech roles, called out for you.** Rolecall crawls thousands of job postings every
day straight from company job boards, works out the level, role, skills, location and pay
of each one, and ranks them against your resume, with the reason for every match. It is
built for Indian students and freshers hunting internships and new-grad roles across
software, ML/AI, data and infra, in Indian cities or remote.

- **Scorecard**: a personalised feed. Every role gets a match score plus the skills it
  matched, whether the level fits, where it is, and red flags ("asks for 3+ years").
- **Search**: plain-language search; keyword and semantic retrieval fused, then reranked.
- **Tracker**: saved → applied → OA → interview → offer, drag and drop, exports to Excel.
- **Assistant**: a tool-using LLM agent that searches the live index, compares roles,
  updates your tracker, sets alerts and remembers your preferences across chats.
- **Multiple resumes** (e.g. SWE and ML), **daily email digest**, **saved-search alerts**.
- **Public evals** page: ranking quality measured against the live index.

Runs entirely on free tiers: local ONNX embeddings, free LLM APIs (Groq, Gemini,
Cerebras, OpenRouter) or a local model, Postgres + pgvector, a free VM or free PaaS.

---

## Architecture

```mermaid
flowchart LR
  subgraph Sources
    ATS[Greenhouse / Lever / Ashby /<br/>Workable / SmartRecruiters /<br/>Recruitee / Workday]
    AGG[HN Who's Hiring /<br/>Remotive / Arbeitnow / RemoteOK]
    WEB[Career pages<br/>JSON-LD JobPosting]
  end
  subgraph Worker
    ING[Polite async crawler<br/>robots.txt, per-host pacing, retries]
    RULES[Rules enrichment<br/>tech filter, level, role, skills,<br/>location, pay, language]
    DEDUPE[Dedupe + stale closing]
    EMB[bge-small embeddings<br/>ONNX on CPU]
    LLMX[LLM refinement<br/>budgeted, cached]
  end
  subgraph Postgres
    JOBS[(jobs<br/>pgvector HNSW +<br/>tsvector GIN)]
    USERS[(users, resumes,<br/>events, tracker, chats)]
  end
  subgraph API[FastAPI]
    RET[Hybrid retrieval<br/>dense + full-text, RRF]
    RANK[Feature ranker<br/>+ cross-encoder rerank<br/>+ personalisation]
    AGENT[Tool-calling agent<br/>memory, summaries]
  end
  WEBAPP[Next.js app]
  ATS & AGG & WEB --> ING --> RULES --> DEDUPE --> JOBS
  JOBS --> EMB --> JOBS
  JOBS --> LLMX --> JOBS
  JOBS --> RET --> RANK --> WEBAPP
  USERS --> RANK
  AGENT --> RET
  WEBAPP <--> AGENT
```

### How a role reaches your scorecard

1. **Discovery.** `rolecall discover` probes ~450 candidate companies against every
   supported ATS's public API and keeps the boards that answer with open jobs
   (224 companies, ~28k raw postings on the first run). Career pages without a known ATS
   are crawled for schema.org `JobPosting` JSON-LD, respecting `robots.txt`.
2. **Ingestion.** An async crawler fetches every board with bounded concurrency,
   per-host pacing and retries. ATS boards return their complete list, so a role missing
   from two consecutive runs is closed; aggregator listings expire by age.
3. **Understanding.** Deterministic rules (fully unit-tested) drop non-tech and
   non-English postings and extract seniority, role family, employment type, work mode,
   cities and countries, ~120 canonical skills, years of experience and pay (INR/LPA,
   USD, stipends). An optional LLM pass refines what the rules can't infer, within a daily
   free-tier budget, cached by content.
4. **Dedupe.** Same company + normalised title + place collapses to one canonical role,
   preferring the company's own board over aggregators.
5. **Indexing.** Each role is embedded locally with `BAAI/bge-small-en-v1.5` into a
   pgvector HNSW index; a weighted `tsvector` (title > company/skills > description)
   powers full-text search.
6. **Retrieval.** Dense (pgvector cosine) and lexical (Postgres FTS) candidates are fused
   with reciprocal rank fusion, under hard filters (level, role, location rules for
   remote-India / remote-worldwide, pay, freshness).
7. **Ranking.** Interpretable features, each in [0, 1] with a plain-language reason:
   semantic similarity, lexical score, skill coverage, level fit, role fit, location
   fit, recency, and affinity to the roles you saved vs hid. A penalty applies when a
   posting asks for more experience than you have. Results are diversified so one
   employer can't flood a page. Search additionally reranks its head with a
   cross-encoder (`ms-marco-MiniLM-L-6-v2`).
8. **Learning from you.** Saves, applies, clicks and dismissals move your query vector
   toward what you like and away from what you hide, and adjust per-company affinity.

### The assistant

An OpenAI-protocol tool-calling loop (every supported provider speaks it) with ten
tools: `search_jobs`, `recommend_jobs`, `get_job_details`, `compare_jobs`, `save_job`,
`list_applications`, `create_alert`, `update_preferences`, `remember`,
`jobs_at_company`. The system prompt carries your profile, preferences and long-term
memories; older turns are summarised to fit free-tier context windows. Replies stream to
the browser as server-sent events (tool steps, then the answer with job cards). Jobs the
model mentions are only rendered if a tool actually returned them, so it can't invent
roles. Per-user daily quotas protect the free tiers.

### LLM router

`app/llm/router.py` tries providers in a configured order, cools a provider down after
a rate limit (honouring `Retry-After`) and falls through to the next, validates structured
output against Pydantic schemas with one repair round, caches deterministic calls in
Postgres, and logs every call's tokens and latency for the admin dashboard. With no keys
at all, everything except the assistant and AI fit checks still works.

---

## Evals

`uv run rolecall eval all` runs four suites and stores results (shown on `/evals`):

| Suite | What it measures |
|---|---|
| **retrieval** | Known-item search: for a stratified sample of live roles, generate the query a student would type (LLM or templates), measure Recall@10/50, MRR@10, nDCG@10 and latency for lexical, dense, hybrid RRF and hybrid + reranker. |
| **recommendation** | Persona feeds (backend new grad, ML intern, data engineer, frontend, SRE). Each variant's top-k is pooled and judged once on a 0–3 scale (LLM judge or transparent rule judge); nDCG@10, P@10, company diversity, coverage. Ablations: dense only, lexical only, RRF only, no experience penalty, no diversity, full ranker. |
| **extraction** | Field accuracy (level, role, work mode, employment type, min years) on hand-labelled real postings: rules vs rules + LLM. |
| **agent** | Scripted conversations with expected tools; tool-selection accuracy, grounding (only real job ids) and pass rate. |

Latest numbers: see [`backend/evals/results/`](backend/evals/results) and [docs/evals.md](docs/evals.md).

---

## Run it locally

Requirements: Docker, Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 20+ with pnpm.

```bash
cp .env.example .env                 # LLM keys optional
docker compose up -d db              # Postgres 16 + pgvector on :5433

cd backend
uv sync
uv run alembic upgrade head
uv run rolecall seed                 # load seeds/companies.yaml
uv run rolecall ingest               # first crawl: ~30 min for ~240 boards
uv run rolecall embed                # local embeddings
uv run uvicorn app.main:app --reload # API on :8000 (docs at /api/docs)

cd ../web
pnpm install
pnpm dev                             # app on :3000, proxies /api to :8000
```

Locally there's a development sign-in (no Google keys needed). Run the worker with
`uv run python -m app.worker` to keep the index fresh on a schedule.

Useful commands: `rolecall discover` (re-probe companies), `rolecall stats`,
`rolecall enrich-llm`, `rolecall reenrich`, `rolecall eval <suite>`, `rolecall digest --email you@x.com`.

Tests: `uv run pytest` (unit tests plus end-to-end API tests against Postgres),
`pnpm lint && pnpm exec tsc --noEmit` in `web/`.

## Deploy for free

See [docs/deploy.md](docs/deploy.md): Next.js on Vercel's free tier; API, worker and
Postgres on an Oracle Cloud Always Free VM with Docker Compose and Caddy (automatic TLS).
A card-free alternative runs the API on a free PaaS with Neon Postgres and does ingestion
on scheduled GitHub Actions.

## Repository layout

```
backend/
  app/ingest/      crawler, ATS adapters, discovery, pipeline
  app/enrich/      rules, skills taxonomy, locations, embeddings, LLM refinement
  app/search/      filters, hybrid retrieval, ranker, personalisation, engine
  app/agent/       tools and the agent loop
  app/llm/         multi-provider router
  app/evals/       eval suites
  app/api/         FastAPI routers
  seeds/           candidate companies and discovered boards
  tests/
web/               Next.js app (App Router, Tailwind)
infra/             production compose, Caddy, Postgres init
docs/              architecture decisions, evals, deployment
```

## Design decisions

Short records of the important trade-offs live in [docs/decisions](docs/decisions):
why Postgres for everything, why rules before LLMs, hybrid retrieval with RRF, an
interpretable ranker before learning-to-rank, free-tier LLM routing, and the crawler's
politeness rules.
