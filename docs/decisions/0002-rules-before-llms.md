# 2. Deterministic rules first, LLM refinement second

## Context
Every posting needs structured fields (tech or not, level, role family, skills,
location, remote scope, years, pay). Thousands of new postings arrive daily, and free LLM
tiers allow a few hundred to a few thousand calls a day with rate limits.

## Decision
A rules layer runs on every posting at ingest: title and description regexes, a curated
skills taxonomy with ~120 canonical skills and context-sensitive patterns (`Go`, `R`,
`Swift`), location gazetteers with ISO countries and remote regions, salary parsers for
INR/LPA/USD/stipends, and a language filter. It is pure Python, unit-tested and
versioned (`RULES_VERSION`); bumping the version re-enriches changed jobs.

An LLM pass then fills gaps the rules can't (unstated seniority, a one-line summary,
extra skills) for the roles users are most likely to see first (early-career, India or
remote, newest), within a daily budget, with responses cached by content hash.

## Consequences
- The product works with zero LLM access; LLMs improve quality rather than gate it.
- Rules are fast enough (~20 ms per posting) to rerun over the whole index.
- Field accuracy is measured against hand-labelled postings for both variants
  (`rolecall eval extraction`), so the LLM's contribution is a number, not a belief.
