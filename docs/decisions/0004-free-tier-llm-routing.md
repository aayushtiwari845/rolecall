# 4. A provider-agnostic LLM router over free tiers

## Context
Budget is zero. Free tiers (Groq, Gemini, Cerebras, OpenRouter free models) have tight,
different rate limits and occasional outages; a local model (Ollama on a 6 GB laptop GPU)
is available for batch work.

## Decision
All providers are used through the OpenAI chat-completions protocol, which each of them
supports, so one client type covers every provider. The router:
- tries providers in a configurable order, each with a `fast` and a `smart` model;
- puts a provider in cooldown on 429 (honouring `Retry-After`), on auth errors for an
  hour, and on network errors briefly, and falls through;
- requests JSON mode for structured output, validates with Pydantic, and asks once for a
  repair with the validation error;
- caches deterministic calls (extraction, explanations, eval judgements) in Postgres;
- records every call for the admin dashboard.

## Consequences
- Losing any single provider degrades latency, not availability.
- No provider-specific features (native JSON schema mode, parallel tool calls) are
  assumed; the repair round covers models that drift from the schema.
- Tests use a scripted fake client, so router behaviour (fallback, cooldown, repair)
  is covered without network access.
