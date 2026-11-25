# 1. Postgres (with pgvector) for jobs, vectors, full-text search and app data

## Context
The system needs relational data (users, tracker, events), a vector index for semantic
search over ~10–30k live roles, full-text search, and must run for free on one small VM.

## Decision
One Postgres 16 with the `pgvector` extension. Jobs carry a 384-d embedding with an HNSW
index (cosine) and a generated, weighted `tsvector` with a GIN index. Hard filters
(level, location, freshness) run in the same SQL as the vector or text search.

## Consequences
- One backup, one connection pool, transactional consistency between a job's fields and
  its vector; filters and retrieval in one query.
- `ts_rank_cd` is not true BM25. At this corpus size the gap is small, and the lexical
  side only needs to be good enough to feed rank fusion. ParadeDB (`pg_search`) is the
  upgrade path if lexical quality becomes the bottleneck.
- HNSW with filters can under-return; we enable iterative index scans
  (`hnsw.iterative_scan`) and over-fetch candidates.
- A dedicated vector DB (Qdrant, Pinecone) would add an operational dependency for no
  measurable gain at this scale.
