# How the recommender is evaluated and tuned

This is the methodology behind the numbers on `/evals` and in `backend/evals/results/`.
Everything here is reproducible from the repository:

```bash
uv run rolecall pool                 # pool unjudged (persona, role) pairs from 8 rankers
uv run rolecall judge-add grades.json  # import 0-3 judgements for the pooled sheet
uv run rolecall eval-recsys --split test   # judged evaluation with CIs and segments
uv run rolecall tune --trials 300          # two-stage tuning on dev, validated on test
uv run rolecall eval all && uv run rolecall eval-report
```

## 1. What "good" means here

A feed is good for a student if the top of it holds roles they would apply to today:
the right kind of work, the right level, a location they can actually take, and skills
they have. It is bad if it wastes their top slots on senior roles, on remote roles that
only hire in the US, or on twelve roles from one company. The metrics below each
measure one of those.

## 2. Ground truth: judged personas (TREC-style pooling)

- **16 personas** (`backend/evals/data/personas.yaml`): interns, new grads, juniors, one
  experienced engineer; backend, ML, LLM, data, frontend, infra, security, mobile,
  embedded, QA; Indian cities and remote-only; one deliberately sparse profile; one
  matching the project owner's resume. Each has a text profile, skills, years of
  experience, target levels, role kinds and cities.
- **Split:** 10 dev personas for tuning, 6 test personas only for reporting. Groups are
  balanced so test covers intern, new grad, junior, experienced, remote and India.
- **Pooling:** for each persona, the top 10 of eight deliberately different rankers
  (dense only, lexical only, fusion only, hand-set defaults, skills-heavy,
  semantic-heavy, level-heavy, MMR-diversified) are unioned. 408 pairs.
- **Judging:** every pair graded 0-3 against a rubric written before judging (in
  `backend/app/evals/judged.py`), reading the posting's title, company, location and
  eligibility, level, required experience, skills and description, without seeing any
  ranker score. 3 = would apply today; 2 = good with one minor gap; 1 = marginal; 0 = not
  relevant (wrong role, clearly too senior, ineligible location).
- **Iterative pooling:** a tuned configuration can surface roles nobody judged. Metrics
  are computed on judged roles only ("condensed" lists, Sakai 2007) plus bpref, which is
  robust to missing judgements, and judged@10 is reported so gaps are visible. The tuner
  penalises configurations whose top 10 is less than 60% judged. Before final numbers,
  the tuned configuration's results are pooled and judged too.

## 3. Metrics

Accuracy (graded relevance): nDCG@5/10/20, P@10 (grade >= 2), MAP, MRR, bpref,
Success@5 (a grade-3 role in the top five).

Beyond accuracy:
- **violations@10**: share of the top 10 that breaks a hard expectation: a level the
  persona excluded (a senior role for a student, or an intern role for a senior), more
  than two years of experience beyond theirs, or a location they cannot take.
- **ild@10**: intra-list diversity, 1 - mean pairwise cosine similarity of the shown roles.
- **companies@10**: distinct companies in the top 10; **exposure Gini** across personas.
- **median_age_days** of the top 10 (freshness) and **coverage** of the catalogue.
- **stability_rbo**: rank-biased overlap between a persona's feed and the feed after
  removing one skill from their profile. Small profile edits should not reshuffle
  everything.
- **latency_ms** of the full `recommend()` call.

Statistics: every metric is a mean over personas with a 95% percentile bootstrap
interval (2,000 resamples). Two configurations are compared with a paired randomisation
(sign-flip) test over personas (10,000 permutations), with wins and losses counted.
Every metric is also broken down by persona group (intern / new grad / junior /
experienced, role area, India city / remote, sparse profile).

## 4. Search evaluation

Known-item search: for a stratified sample of live roles, write the query a student
would type for that role (an LLM writes them when a key is configured, otherwise
templates over the role's fields), then measure where the role (or a duplicate of it)
lands: Recall@10/50, MRR@10, nDCG@10, and p50/p95 latency, for keyword only,
embeddings only, fused, and fused + cross-encoder reranking.

## 5. Tuning

All tunable numbers live in one configuration object (`Weights` in
`backend/app/search/rank.py`): feature weights, feature shapes (similarity calibration,
skill saturation, level and role partial credit, freshness decay), the experience
penalty (slack, step, floor), diversity (MMR lambda, per-company cap and window),
retrieval depths, fusion and reranking.

1. **Retrieval** (grid): dense and lexical candidate depths, scored by *candidate
   recall*, the share of judged-relevant roles that reach the candidate set at all,
   against latency. The smallest pool within 1% of the best recall wins.
2. **Ranking** (Optuna TPE, multivariate, seeded, 300 trials, trial 0 = current
   defaults): 22 parameters, on dev personas only, objective
   `0.5 * nDCG@10 + 0.5 * strict nDCG@10 - 0.5 * violations@10`. Condensed nDCG rewards
   ordering the judged roles well; strict nDCG counts unjudged roles as not relevant,
   so a configuration cannot win by surfacing roles nobody graded. Candidates are
   cached per persona, so each trial costs milliseconds. Parameter importances are
   recorded.
   - **Selection against the winner's curse:** the best of 300 trials on ten personas is
     an optimistic estimate. The ten best trials are re-scored per persona and the one
     with the highest lower bound (mean minus standard error) is chosen, preferring a
     gain that holds across personas over a larger one carried by two of them.
   - **Iterative pooling:** the five best configurations' top 10s are pooled, judged and
     added to the qrels, then tuning is rerun, until the chosen configuration's results
     are almost fully judged.
3. **Search** (grid with cached hits and reranker scores): RRF constant, lexical weight,
   rerank head size and blend, under a 250 ms reranking budget. The cross-encoder's
   per-document cost is measured on real documents after a warm-up call (an early
   version timed the model load and wrongly ruled reranking out).
4. **Validation**: the winner is compared with the defaults on the 6 held-out test
   personas with the paired test. It ships (`backend/app/search/tuned_config.json`,
   loaded by `load_config()`) only if it is not worse on test and does not add
   violations. The file records dev and test metrics, the search space, seed, trials
   and commit.

## 6. Robustness built into the engine

- Cold start: no resume and no history falls back to the freshest roles inside the
  user's filters instead of an empty feed.
- Over-narrow preferences: widened step by step (cities, then role kinds, then
  freshness) and every widened-in role says "Outside your preferences: ...".
- Failures: vector-query timeouts (`statement_timeout`) and database errors fall back to
  fresh roles; embedding or reranker failures fall back to keyword search or fused order.
- Determinism: ties break on freshness then id, so pages are stable.
- Property tests (`backend/tests/test_ranking.py`) pin invariants whatever the weights:
  more matched skills never lowers a score, the experience penalty is monotone and
  floored, closer levels score higher, scores stay in [0, 1], ranking is independent of
  candidate order, diversity steps never drop items.

## 7. Known limitations

- Judgements come from a single judge pass per pair, not multiple annotators, so
  inter-annotator agreement cannot be reported yet. The rubric and every judgement are
  in the repository for anyone to audit or re-judge.
- 16 personas give wide confidence intervals. Differences smaller than the intervals are
  reported as such, not as wins.
- Retrieval depth tuning uses pools built at the default depths, which biases
  candidate recall toward depths at or below them.
- Offline metrics are a proxy. Once there is real traffic, feed impressions with
  positions are logged, so `rolecall train-ranker` can fit weights from clicks and saves
  and online metrics (CTR, save rate) can be compared per configuration.
