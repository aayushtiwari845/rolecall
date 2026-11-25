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
  semantic-heavy, level-heavy, MMR-diversified) are unioned: 408 pairs, plus 100 more from two rounds of
  pooling the tuned configurations (508 in all).
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

## 5a. Tuning log (what actually happened)

Each round's full report is in `backend/evals/results/tuning_history/`. The test personas
are only used for the ship decision; every look at them is listed here.

| Round | Change | Dev nDCG@10 (default → tuned) | Test nDCG@10 (default → tuned) | Shipped |
|---|---|---|---|---|
| 1 | 22 params, objective on condensed nDCG | 0.616 → 0.824 | 0.630 → 0.602, judged@10 0.67 | no |
| 2 | +72 judgements from round 1's results; strict nDCG in the objective; lower-bound trial selection | 0.584 → 0.776 (p=0.004) | 0.624 → 0.512 (p=0.12) | no |
| 3 | +28 judgements; nested 5-fold CV inside dev picks the search space | 0.584 → 0.789 (p=0.002) | 0.624 → 0.559 (p=0.34) | no |
| 4 | space chosen by CV lower bound (trust region); search split fixed | 0.584 → 0.753 (p=0.002) | 0.624 → 0.602 (p=0.75) | ranking no; retrieval and search yes |

**What shipped after round 4** (decided stage by stage by `release()` in
`backend/app/evals/tune.py`, reproducible with `rolecall tune-release`):

| Stage | Decision | Evidence on held-out data |
|---|---|---|
| Feed retrieval depth | 200 dense, 0 lexical (was 300 + 150) | test nDCG@10 identical (0.624), candidate recall 0.98 both, feed latency 231 → 152 ms |
| Ranking weights | stay hand-set | CV gain inside dev (+0.12, p=0.03) did not hold on test (-0.022, p=0.75) |
| Search fusion | RRF k 30, lexical weight 2, no cross-encoder | 40-doc rerank measured at ~2.2 s on CPU, far over the 250 ms budget; dropping it moves test MRR@10 0.210 → 0.200 (p=0.72) |

The cross-encoder stays in the code and in the search eval as a variant: on a GPU or a
faster host, set `rerank_head` back above zero.

The honest summary: on 16 personas, Bayesian optimisation of the ranking weights finds
real gains on personas it was tuned on (and, by nested CV, on unseen *dev* personas), but
not on the held-out set. The hand-set weights are as good as anything the tuner found
within the noise of this evaluation. Getting a reliable gain needs more personas or real
interaction data (`rolecall train-ranker`), not more trials.

What each round taught:
- **Round 1:** the tuned ranker had pushed unjudged roles into the top 10 (only 67% judged
  on test). Condensed metrics hid that. Fix: pool and judge those roles, and add strict
  nDCG (unjudged = not relevant) to the objective.
- **Round 2:** a large, significant dev gain did not transfer. 22 parameters on 10
  personas overfit. The newly judged roles also exposed junk postings (developer
  engagement "representatives", equity-only HN posts, crowdtesting gigs), now filtered.
- **Round 3:** nested CV *inside dev* said tuning generalises to unseen dev personas
  (+0.135 objective [0.015, 0.256] for the full space; +0.117 [0.038, 0.193], p=0.025,
  for a 12-parameter trust region around the defaults), yet the full-space winner still
  lost on test (2 wins, 4 losses, not significant). Two lessons: with 16 personas the
  noise floor is around ±0.1 nDCG; and the space should be chosen the same way trials
  are, by lower bound rather than mean.
- **Two bugs found by the tuner:** MMR was O(n³) Python (10 s per trial, and slow feeds
  whenever diversity was on): now vectorised, 25-50x faster, identical output, pinned by
  a reference test. The search stage's dev/test split put whole role families on one
  side (the sampler interleaves families round-robin), which made dev and test disagree
  with p=0.02: now alternated within each family.
- **Disclosure:** the rule "choose the space by lower bound" was adopted after seeing
  round 3's test result. The test personas have now informed four ship decisions, so
  treat their numbers as validation rather than a pristine test. A fresh test set means
  new personas judged from scratch (see limitations).

## 5b. Fresh held-out personas (pre-registered)

The 6 test personas informed four ship decisions, so their numbers are validation, not a
clean test. Twelve new personas (`split: fresh` in `personas.yaml`) were written after
round 4, before any of their roles were pooled or judged: a Java intern in Pune, a remote
NLP research intern, a data analyst in Chennai, a cloud intern, a junior Android developer,
a Go new grad, a MERN intern in Delhi NCR, a 3-year MLOps engineer, a senior remote
frontend engineer, a C++ systems new grad, a junior application-security engineer and a
data-science new grad. None of them is ever used for tuning.

Plan, fixed before pooling and committed with the personas:

- **Pool:** the eight standard rankers, the released configuration, the tuned
  configurations of rounds 2, 3 and 4 and round 4's five best trials, depth 10, so every
  compared configuration's top 10 is fully judged. Each persona's sheet is shuffled, so the
  judge cannot tell which ranker found a role, and is graded against the same rubric.
- **Primary comparison:** released configuration (hand-set ranking weights) vs round 4's
  tuned ranking weights, nDCG@10 on the 12 fresh personas, paired randomisation test.
- **Secondary:** rounds 2 and 3's tuned weights; strict nDCG@10, P@10, bpref,
  violations@10.
- **Decision rule:** the same as `release()` stage 2. Round 4's weights ship if fresh
  nDCG@10 is not worse (delta >= -0.005) and violations@10 do not rise. Otherwise the
  hand-set weights stay.
- **One look:** each configuration is evaluated on the fresh set once (`rolecall
  eval-fresh`). The result is reported whatever it is, and the fresh set then becomes
  validation data like the test set.

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
- The 6 test personas have informed four ship decisions. The next step for a clean
  estimate is a fresh set of personas, judged from scratch and used once.
- Judgements cover 508 (persona, role) pairs across four pooling rounds; roles a future
  configuration surfaces will need judging again (judged@10 is reported for that).
- Retrieval depth tuning uses pools built at the default depths, which biases
  candidate recall toward depths at or below them.
- Offline metrics are a proxy. Once there is real traffic, feed impressions with
  positions are logged, so `rolecall train-ranker` can fit weights from clicks and saves
  and online metrics (CTR, save rate) can be compared per configuration.
