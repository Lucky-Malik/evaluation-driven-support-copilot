# Phase 3 — Evaluation harness and failure analysis

## 1. What we built and why

The vector-only Phase 2 pipeline now has a repeatable evaluation workflow. It validates a versioned dataset, runs selected questions through the existing application, measures retrieval and response behavior, asks a structured LLM judge about qualitative properties, and saves enough context to inspect individual failures. Run comparison and a user review packet make the results reviewable before changing retrieval.

The starter dataset contains **30 agent-inspected cases: 20 development and 10 held-out test cases**. Its four categories are ordinary questions (12), exact identifiers (8), ambiguity (4), and missing evidence (6). Twenty answerable cases contain 21 labelled evidence references. All labels are agent-authored and agent-inspected; **zero cases are user-reviewed**. The [dataset guide](../../data/evaluation/fastapi-support-v1/README.md) describes inspection and expansion toward 100 reviewed cases.

The offline validation artifact is [offline-validation.json](offline-validation.json). It establishes dataset integrity, not model quality. No live benchmark or real judge-review agreement has been measured because `OPENAI_API_KEY` is absent. The actual database still has 81 chunks and zero embeddings.

## 2. What remains for later

Phase 4 will add PostgreSQL full-text and hybrid retrieval, filters, adversarial cases, and measured guardrail experiments. Phase 5 will add the Streamlit interface/dashboard, CI, deployment packaging, and portfolio results. This phase leaves the baseline retrieval and answer prompt unchanged. It adds failure evidence to internal exceptions so evaluation can inspect requests that failed after retrieval.

## 3. Concepts and metric definitions

The unit of relevance is a **labelled chunk ID**, not a document, sentence, or citation. Let `G` be the set of relevant chunk IDs and `R[:K]` the ranked retrieved list, truncated to the configured K.

| Measurement | Definition and denominator |
| --- | --- |
| Recall@K | `len(set(R[:K]) & G) / len(G)` for answerable cases with completed retrieval. |
| MRR@K | Mean of `1 / rank` of the first relevant chunk in the top K, or 0 if absent. Each case stores its reciprocal rank. |
| Outcome accuracy | 1 if the returned status matches the labelled status, otherwise 0. Application errors count as 0. |
| Citation validity | Fraction of returned citations whose chunk ID and URL match a retrieved passage. An answered response with no citations scores 0. Non-answer outcomes are not applicable. |
| Answer correctness | Judge score against required facts, prohibited claims, and labelled reference evidence. Applicable when the expected outcome is `answered`, including when the candidate incorrectly abstains. |
| Faithfulness | Judge score for support of substantive answer claims by the passages actually retrieved. Applicable when the candidate answers. Gold passages cannot substitute for evidence the application never saw. |
| Citation support | Judge score for whether the actual cited passages support the substantive answer. This is separate from checking that the citation exists. |
| Response appropriateness | Judge score for answering, asking a useful clarification, or abstaining for the right reason. Applicable to every completed answer. |

Qualitative scores are 0 (poor), 1 (partial), or 2 (good), each with a short rationale. Aggregation normalizes them to 0, 0.5, and 1. The exact rubric is [judge-v1.txt](../../src/support_copilot/prompts/judge-v1.txt). A wrong outcome receives 0 for response appropriateness; correct but vague clarification can receive 1.

For a hand calculation, let `G={a,b,c}`, `R=[x,b,y]`, and `K=3`: Recall@3 is `1/3` and reciprocal rank is `1/2`. If `R=[x,x,b]`, rank is still 3: duplicates consume ranks but never inflate recall. Cases without positive labels have `null` retrieval metrics, not a perfect or zero score. Retrieval that never completed is also `null`.

Every aggregate includes its eligible count `n`. Judge failures produce `null` qualitative scores and separate failure counts, not zero-quality answers. Application errors can therefore reduce score coverage. Read coverage and error rates alongside averages; a high mean over a small surviving subset can mislead. Category breakdowns expose differences between ordinary and exact-identifier questions, for example.

Application latency and judge latency are separate, measured with a monotonic clock. Summary p50 is the median; p95 uses the nearest-rank element `ceil(0.95*n)`. Application traces also retain stage times. Usage totals include only provider-reported tokens and disclose missing usage. Application and judge usage are never added into one application-cost figure. Both estimated dollar costs remain `null` because no verified pricing configuration is enabled; missing usage does not mean a call was free.

## 4. A concrete data flow

Consider the development case asking how an integer `item_id` path parameter behaves when the path contains `foo`.

1. `load_dataset` verifies the dataset files, snapshot identity, chunking version, and the exact quotes in the two labelled chunks. The full saved HTML is available locally; source websites are not fetched during evaluation.
2. Before any model call, `verify_database` checks complete embedding coverage and compares the stored chunk IDs, hashes, and text with the reconstructed snapshot.
3. The unchanged baseline embeds the question, retrieves the top K chunks, and generates a structured answer. It never receives the case's expected status or answer criteria.
4. Deterministic checks compare the retrieved IDs with the labels and validate the returned outcome and citations. The judge receives the question, criteria, reference evidence, retrieved evidence, and candidate in a JSON data payload under a separate rubric.
5. The runner flushes a case record containing the input, both evidence sets, answer/error, timings, usage, scores, and failure tags. The summary groups scores by category.
6. A review packet can later show the full case and judgment to the user. Recording agreement creates a separate review file; it does not rewrite the run or dataset labels.

This is an explanation of the implemented flow, not a reported live result for that question.

## 5. Important files

| File | Responsibility |
| --- | --- |
| `data/evaluation/fastapi-support-v1/manifest.json` | Pins source snapshot, pipeline, relevance unit, and dataset file hashes. |
| `dev.jsonl` and `test.jsonl` in that directory | Questions, expected statuses, evidence quotes, criteria, families, and review provenance. |
| `src/support_copilot/evaluation/dataset.py` | Typed dataset validation and exact local evidence reconstruction. |
| `evaluation/metrics.py` | Deterministic formulas, eligible counts, category summaries, latency and usage. |
| `evaluation/judge.py` | Judge settings, strict response schema, provider call, and failure handling. |
| `evaluation/runner.py` | Database preflight, per-case evaluation, run persistence, and compatible-run comparison. |
| `evaluation/artifacts.py` | JSON writes, code/environment identity, and result-integrity checks. |
| `evaluation/review.py` | Repeatable category-stratified sampling and validated review recording. |
| `evaluation/cli.py` and `src/support_copilot/cli.py` | `copilot eval` commands and safe CLI errors. |
| `config/judge-v1.json` and `prompts/judge-v1.txt` under the package | Versioned judge model settings and rubric. |
| `rag.py`, `errors.py`, and `contracts.py` | Preserve retrieved passages/raw drafts on application failures and identify judge usage. |
| `tests/evaluation/` and `tests/test_rag.py` | Dataset, metric, provider, artifact, review, database, and failure-path tests. |

Package/API version is now 0.3.0. `.env.example` exposes `COPILOT_JUDGE_MODEL`; `runs/` is ignored by Git so paid-run content is an intentional sharing decision.

## 6. How the main functions fit together

`validation_report` uses `load_dataset` and `corpus_passages`; it needs no database or provider. `run_evaluation` selects a split, verifies the indexed corpus, and calls `evaluate_case` sequentially. `evaluate_case` calls the existing `answer_question`, computes `deterministic_scores`, and calls `judge_answer` only after a usable application answer exists. `summarize` aggregates the results without filling missing scores with zero.

`compare_runs` reads completed, checksummed artifacts and requires matching dataset, corpus, split, case order, metric version, judge configuration, and rubric. It reports paired metric deltas only for cases scored in both runs, with `n_pairs`, plus the complete summaries and application settings. Application settings and answer prompts may differ: that is what an experiment compares. It does not perform significance testing or automatically choose a winner.

`prepare_review` orders successful judgments by a seeded hash within categories, then takes cases round-robin across categories. `record_review` checks packet types, run identity, unchanged result context, reviewer identity, and decisions. New UUID-named review files preserve previous submissions.

## 7. Commands and expected behavior

Run from the repository root. Install with `uv sync --locked`, then perform the free validation:

```bash
uv run copilot eval validate
uv run copilot eval validate --report docs/phase-3/offline-validation.json
uv run pytest -m 'not integration and not live' -q
```

Validation prints 30 cases, 20/10 split counts, 81 corpus chunks, 21 evidence references, and `model_calls: 0`. Editing a JSONL file without updating its version/checksum is rejected.

For live evaluation, first configure `OPENAI_API_KEY` in the local `.env`. Use the existing localhost database setup from the root README. These commands make paid calls:

```bash
docker compose up -d --wait
uv run copilot init-db
uv run copilot ingest --snapshot data/snapshots/fastapi-d4f83a093dd1b2ab
uv run copilot embed
uv run copilot eval run --split dev --limit 2 --output runs/dev-smoke
uv run copilot eval run --split dev --output runs/baseline-dev
```

A completed case normally uses one question-embedding call, one answer-generation call, and one judge call: 60 calls for 20 development cases, excluding corpus indexing. Defaults cap application output at 4,096 tokens and judge output at 3,072, with low reasoning effort, 45-second per-call timeouts, and no SDK retries. Runs are sequential and limited to at most 100 selected cases. These are bounds on workload, not a dollar-cost estimate or a whole-run deadline. `--limit` takes the first N cases in split order; a small smoke run is not a representative sample.

Use a new output directory each time. A run contains:

```text
run.json                 IDs, timestamps, status, config/model/prompt/source hashes
dataset_manifest.json    pinned corpus and dataset-file identities
selected_cases.json      exact evaluated labels and their provenance
answer_prompt.txt        application instructions used
judge_prompt.txt         rubric used
cases.jsonl              complete per-case evidence, answer/error, scores and usage
summary.json             overall/category metrics, failures, latency, separate usage
reviews/<uuid>.json      optional submitted user review decisions
```

Requested and returned provider model IDs are recorded, along with request IDs when available. Environment identity records Python and core package versions plus hashes of package code/configuration. Configured model aliases can change upstream, so this identifies an experiment but does not promise bit-for-bit provider reproducibility.

To exercise comparison after a baseline exists, run a separate development experiment:

```bash
COPILOT_TOP_K=3 uv run copilot eval run --split dev --output runs/dev-k3
uv run copilot eval compare runs/baseline-dev runs/dev-k3
```

Read the reported K values when interpreting Recall@K: changing K changes the retrieval budget. This command demonstrates comparison; no improvement from K=3 has been measured. Once development choices are frozen, explicitly select `--split test` with a new output directory for the held-out measurement.

Review actual successful judge decisions with:

```bash
uv run copilot eval review-sample --run runs/baseline-dev --output runs/review.json --count 5 --seed 42
```

Open `runs/review.json`, enter your name in `reviewer`, and read each full `result`. Set `decision` to `agree`, `disagree`, or `unable_to_assess`; provide notes explaining disagreements or uncertainty, identifying the metric and evidence. Leave unfinished items `pending`. Edit only reviewer, decisions, and notes, then run:

```bash
uv run copilot eval review-record --run runs/baseline-dev --packet runs/review.json
```

Agreement is `agree / (agree + disagree)` for submitted decisions; unable-to-assess decisions are counted separately and pending items are omitted. The category-stratified sample is for inspection, not an unbiased estimate of all judge decisions. Sampling records zero reviews until decisions are submitted. No real judge decisions or user agreement are recorded in this phase.

## 8. Checks performed and actual results

Verification was performed on 10 November 2026. The dataset validator passed with all 30 cases agent-inspected and zero model calls. A live smoke-run command was attempted and exited with the expected missing-key message: `Set OPENAI_API_KEY on the server to enable paid calls.` No benchmark was produced.

The automated tests use scripted HTTP responses through the real OpenAI SDK. They verify hand-calculated recall/MRR, duplicate ranks, citation URL mismatches, null applicability, malformed/refused/incomplete judge output, retained token usage, provider errors, interrupted runs, result checksums, paired comparison coverage, and review provenance/context protection. PostgreSQL integration tests use isolated temporary schemas and verify missing embeddings and stored-corpus tampering are rejected.

Run the full suite locally with:

```bash
TEST_DATABASE_URL=postgresql://copilot:local-development-only@127.0.0.1:5433/copilot uv run --locked pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
git diff --check
```

Final result: **94 passed, 3 paid live tests skipped, 1 warning**, in 10.84 seconds, including PostgreSQL integration tests. Ruff lint and formatting checks passed across 38 Python files; `git diff --check` and local documentation-link checks passed. `uv build --offline` produced the 0.3.0 wheel and source distribution; wheel inspection verified the evaluation modules, judge configuration/prompt, and database schema are packaged.

The first full-suite attempt exposed a duplicate test-module filename, which was fixed. Database checks initially could not connect because Docker was stopped; Docker and the project database were started before the successful run. A final regression test distinguishes a failed retrieval stage with recorded timing from successfully completed retrieval, so failures do not become artificial retrieval misses. Scripted test answers and review decisions are temporary fixtures; they are not benchmark evidence or human review. The existing Starlette TestClient deprecation warning remains visible.

## 9. Decisions and tradeoffs

We use plain Python, Pydantic models, JSONL, and the official SDK instead of an evaluation framework. This keeps formulas and failures inspectable while accepting a small amount of explicit artifact code. Gold labels include exact quotes so readers can audit them; criteria allow equivalent wording instead of brittle string matching.

The judge defaults to `gpt-5.6-terra` and is separately configurable through `COPILOT_JUDGE_MODEL`. Its structured JSON schema uses the Responses API, with local validation after capturing usage so malformed judgments do not erase known billing evidence. Current API/model support was checked on 10 November 2026 against the official [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs) and [model page](https://developers.openai.com/api/docs/models/gpt-5.6-terra). No dated model snapshot or price has been invented.

Using the same default model family for answering and judging simplifies setup but can create correlated mistakes and stylistic preference. A different judge is a useful future experiment, not automatically a more accurate one. The saved rubric and user review are needed to diagnose judge behavior. No local heuristic is presented as a substitute for semantic correctness.

The runner continues after known application/provider failures so a benchmark exposes error rates. Unexpected programming errors propagate and leave an interrupted artifact; they are not silently converted into a score. A completed run means all selected cases were processed, not that all calls succeeded. Completed runs with judge failures remain comparable with explicit coverage counts.

## 10. Failure cases and limitations

- Labels are small, agent-authored, and not exhaustively adjudicated. Valid alternative evidence may be unlabelled, depressing strict chunk recall even when an answer is useful. User review and broader coverage are required before strong claims.
- Missing-evidence labels concern this six-page snapshot, not all FastAPI capabilities. Clarification labels encode a policy choice about when missing detail warrants a follow-up.
- Dataset family checks catch declared overlap, not every semantic paraphrase. The held-out set is reserved and visible, not an independently administered blind benchmark.
- Judge instructions treat the entire payload as untrusted data and provide no tools, but prompts and schema validation do not guarantee resistance to prompt injection or correct judgment. Adversarial measurement belongs to Phase 4.
- The rubric gives one score per dimension for the whole answer, not claim-by-claim annotations. A valid citation may be irrelevant; an answer may be correct from prior knowledge but unfaithful to the retrieved evidence.
- No verified prices, paid baseline, live judge behavior, or human agreement rate are available yet. Failure-count and coverage fields must accompany any future quality report.
- Artifact hashes detect accidental result changes; they do not authenticate who created a file. Run files contain questions and responses and should be inspected before sharing. The prototype has no multi-tenant controls.
- Existing output directories are refused. There is no resume mechanism for interrupted evaluations; preserve the partial artifact and start a new run. A hard process kill may leave status `running`, which comparison/review rejects.

## 11. Five interview questions

**Why evaluate before adding hybrid retrieval?** A fixed baseline, labelled cases, and comparable artifacts make it possible to attribute an observed change to a specific experiment. We have built that measurement path; we have not yet observed a live improvement.

**Why distinguish recall and MRR?** Recall measures coverage of the labelled relevant chunks, while MRR rewards finding the first relevant chunk early. A case needing two passages can have excellent MRR and incomplete recall.

**How can a citation be valid but unsupported?** It can reference an actual retrieved chunk with the correct URL while that chunk says nothing about the answer's central claim. Membership is deterministic; support needs semantic assessment and review.

**How do you avoid pretending the judge is ground truth?** Its rubric, model, rationales, failures, eligible counts, and separate usage are saved. A user can inspect a category-stratified sample and record disagreement. No human review or agreement rate is claimed before that happens.

**What makes a run reproducible, and what remains uncertain?** The dataset/corpus/config/prompt/source identities, selected cases, provider model IDs, outputs, and package versions identify the experiment. Hosted model aliases and nondeterminism can still change later answers; hashes cannot guarantee identical future generation.

## 12. Hands-on exercise

Without a key, choose one answerable case in `dev.jsonl`. Read its quoted chunks and manually calculate Recall@3 and reciprocal rank for a made-up ranking containing one irrelevant chunk before a relevant one. Compare your calculation with `tests/evaluation/test_metrics.py`. Then copy the dataset to a temporary directory, change one quote, update that copy's file checksum, and run `eval validate --dataset <copy>`: it should reject the quote independently of checksum validation.

After configuring a key and completing a development run, review five judge decisions. For one disagreement, state which score you contest and quote the evidence that changes your assessment. Record the review without editing the saved result. This makes the distinction between an automatic score and an inspected judgment concrete.
