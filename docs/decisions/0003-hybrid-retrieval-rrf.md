# 3. Hybrid retrieval fused with reciprocal rank fusion, then a feature ranker

## Context
Job matching needs both meaning ("model serving" ≈ "ML infra") and exact terms
(library names, "SDE 1", company names). Dense and lexical scores live on different
scales.

## Decision
Two-stage pipeline.

1. **Candidates**: up to 300 dense (pgvector) and 150 lexical (Postgres FTS) hits under
   the same hard filters, fused with RRF (k = 60), which needs ranks only.
2. **Ranking**: interpretable features in [0, 1]: semantic, lexical, skill coverage
   (saturating at 6 strong skills, generic skills like Git ignored), level fit (distance
   on an ordinal scale, unknown levels get partial credit), role fit, location fit,
   recency (21-day decay), and behavioural affinity. A multiplicative penalty applies
   when a role asks for more years than the user has. Then a per-company cap per page.
3. **Search only**: a cross-encoder reranks the top 40 by query relevance.

## Consequences
- Every score decomposes into reasons shown to the user.
- Weights are a dataclass, so evals compare variants and ablations directly.
- With enough interaction data, the same features feed a learning-to-rank model
  (logistic regression or LambdaMART on impressions vs clicks/saves) without changing
  retrieval. Until then hand-set weights are honest about having no training data.
