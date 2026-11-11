# Phase 4 — Retrieval improvements and guardrail experiments

## 1. What we built and why

The copilot now supports three retrieval modes: the preserved vector baseline, PostgreSQL keyword search, and hybrid search using reciprocal rank fusion (RRF). Snapshot and exact section filters apply before ranking. Run artifacts capture the selected mode, candidate budget, fusion constant, filter, and individual retrieval scores/ranks.

The application also bounds question, HTTP body, generation, and judge input sizes. A separate twelve-case adversarial dataset exercises question/document injection and benign controls using the production generation function and citation validator. It records both narrow attack signals and unnecessary refusal of valid questions, with application errors kept separate.

The purpose is to make retrieval and guardrail choices testable. **Vector remains the default.** Real keyword retrieval was measured; vector/hybrid and live adversarial measurements are blocked by the absent API key. See [results and inspected failures](results.md), rather than treating implementation as evidence of improvement.

## 2. What remains for later

Phase 5 will add the Streamlit question interface and evaluation dashboard, CI/regression workflows, application packaging for deployment, and portfolio delivery. There is no authentication, tenant isolation, deployment, or security certification here. Reranking is intentionally omitted: we have no measured hybrid-versus-vector failures that justify an extra model or ranking stage.

## 3. Concepts in plain language

**Keyword retrieval** matches normalized words from a question to indexed documentation. This implementation uses PostgreSQL's English text-search configuration, which stems words and removes stop words. It assigns section text weight A and body text weight B, combines question lexemes with OR to avoid requiring every word in a natural-language question, and orders matching chunks by `ts_rank_cd` with chunk-ID tie breaking. A stored generated `tsvector` and GIN index stay synchronized with chunk text. These APIs and storage behavior follow the official [text-search controls](https://www.postgresql.org/docs/17/textsearch-controls.html) and [tables/indexes](https://www.postgresql.org/docs/17/textsearch-tables.html) documentation. This is PostgreSQL full-text ranking, **not BM25**.

OR matching improves the chance of finding candidates but can favor repeated generic words. Stemming and punctuation parsing mean an identifier is not an exact substring lookup. The first measured failures illustrate these limits; the implementation does not hide them with label changes.

**RRF** combines ranks rather than adding incomparable raw scores. For each candidate chunk, its score is the sum of `1 / (rrf_k + rank)` across the vector and keyword lists. Missing from a list contributes zero. With `rrf_k=60`, a chunk ranked second in vector search and first in keyword search receives `1/62 + 1/61`. A chunk ranked first only in vector search receives `1/61`. Fusion uses distinct chunk IDs and deterministic ID tie breaking, then returns the top K. Defaults retrieve up to 20 candidates from each branch and return five. RRF scores, cosine distances, and keyword scores are rankings, not calibrated confidence.

**Guardrails** enforce specific boundaries. A citation validator can prove a cited ID was supplied and attach its authoritative URL. It cannot prove the cited text supports the answer. Keeping question/evidence in a JSON data payload under separate instructions preserves an explicit trust boundary; it does not make a model immune to injection. Official [OpenAI safety guidance](https://developers.openai.com/api/docs/guides/agent-builder-safety) similarly treats untrusted inputs and structured outputs as risk-reduction measures, not guarantees. We retained the existing `answer-v1.txt` prompt so retrieval comparisons do not also change instructions.

## 4. Concrete request and experiment flows

For “Which exception overrides request validation errors?” in hybrid mode:

1. The API checks the body and question bounds, loads settings, and verifies corpus/index readiness.
2. The provider embeds the question. Exact cosine search retrieves up to 20 candidates within the chosen snapshot/section.
3. PostgreSQL normalizes the same question and retrieves up to 20 keyword candidates with the same filters.
4. RRF combines these rankings and supplies the best five passages to the unchanged structured-answer prompt.
5. The application validates the outcome and citation IDs, attaches URLs from the retrieved passages, and returns evidence, diagnostics, timing, and usage.
6. `eval run` can apply the existing deterministic metrics and semantic judge to this result, using the same development labels as a vector run.

Keyword mode skips the question embedding entirely and requires only an ingested corpus for retrieval. Generation still needs a provider key. The free `eval keyword` command stops after retrieval and scores only Recall@K/MRR on development cases; it does not generate answers.

An adversarial document experiment follows a different, explicit path: it loads pinned reference evidence, appends a synthetic instruction to a copy of one passage, then invokes the production generator and citation validator. There is no retrieval, database mutation, or judge in this controlled experiment. Its artifact kind is `controlled_adversarial_generation`, and ordinary run comparison rejects it. It answers whether a supplied injection can affect generation, not whether the retrieval system would fetch it.

## 5. Important files

| File | Responsibility |
| --- | --- |
| `src/support_copilot/migrations/003_keyword_search.sql` | Generated search vector, GIN index, schema version 3. |
| `src/support_copilot/db.py` | Sequential transactional migration from versions 1 or 2, plus readiness checks. |
| `src/support_copilot/retrieval.py` | Keyword query, shared filters, RRF, hybrid composition, mode-aware readiness. |
| `config/retrieval-v1.json` under the package | Versioned retrieval defaults; the old baseline file remains intact. |
| `settings.py`, `contracts.py`, `rag.py` | Config validation, nullable score fields, mode traces, and mode selection. |
| `guardrails.py`, `provider.py`, `app.py` | Body/payload limits and shared citation validation before returning answers. |
| `evaluation/keyword.py` | Actual free PostgreSQL development retrieval measurements. |
| `evaluation/adversarial.py` | Adversarial validation, copied evidence, generation experiments, refusal/marker metrics. |
| `evaluation/judge.py` | Bounds judge input and records over-limit judge failures separately. |
| `data/evaluation/fastapi-adversarial-v1/` | Twelve versioned attack/control cases and honest review provenance. |
| `tests/test_hybrid.py`, `tests/test_keyword_database.py`, `tests/test_guardrails.py` | Fusion math, real SQL/migration/filter checks, and input-limit behavior. |
| `tests/evaluation/test_adversarial.py` | Controlled attack successes/failures and metric denominators. |
| `docs/phase-4/keyword-dev.json` and `results.md` | Measured keyword evidence and interpretation, with live blockers. |

The package/API version is 0.4.0. The original 30-case evaluation dataset, saved HTML, vector distance calculation, and answer prompt remain unchanged.

## 6. Important functions working together

`initialize` applies migrations in order in one transaction, preserving IDs, text, and embedding rows. `keyword_retrieve` builds a parameterized query from PostgreSQL-normalized lexemes. It quotes each lexeme when constructing the OR expression; raw input is never concatenated into SQL. `retrieve` retains exact cosine ranking with the added optional section filter. `hybrid_retrieve` calls both at the candidate budget, and `reciprocal_rank_fusion` merges their results without modifying input lists.

`answer_question` selects the mode and records the configured parameters. `bounded_payload` measures the UTF-8 JSON bytes sent to generation, while `BodyLimitMiddleware` counts streamed body bytes before JSON parsing. `validated_citations` is shared by the normal API and controlled adversarial runner. Known errors retain the trace/evidence or failed draft when available.

`load_adversarial` validates checksums, reference quotes, attack types, and question bounds. `controlled_passages` deep-copies evidence and recomputes the modified content hash. `evaluate_adversarial_case` records the production generator's outcome and citation validation result. `adversarial_summary` reports narrow marker success, expected-status match, unnecessary refusal, error counts, latency, and reported token usage. It does not silently reinterpret absent scores as successful defenses.

## 7. Commands and expected behavior

Run from the repository root. Preserve your existing `.env`.

```bash
uv sync --locked
docker compose up -d --wait
uv run copilot init-db
uv run copilot eval validate
uv run copilot eval adversarial-validate
COPILOT_RETRIEVAL_MODE=keyword uv run copilot eval keyword --report runs/keyword-dev.json
```

Schema initialization upgrades the existing database to version 3. If starting fresh, follow the root README's ingestion command first. The two validators make zero model calls. The keyword command queries PostgreSQL, selects only the 20 development cases, and writes a new report file. Existing report files are refused. Thirteen cases have positive relevance labels; ambiguity/missing-evidence cases have null retrieval metrics.

Available environment overrides are `COPILOT_RETRIEVAL_MODE=vector|keyword|hybrid`, `COPILOT_TOP_K` (1–20), `COPILOT_CANDIDATE_K` (1–100 and at least K in hybrid mode), `COPILOT_RRF_K` (1–1000), `COPILOT_SNAPSHOT_ID`, and optional `COPILOT_SECTION_FILTER` (an exact full section string). Unset the section variable to search all sections; an empty string is rejected. Settings and filters are configured on the server, not accepted as arbitrary SQL or per-request expressions.

For example, restrict a local server to the required-query-parameters section:

```bash
COPILOT_RETRIEVAL_MODE=keyword \
COPILOT_SECTION_FILTER='Query Parameters > Required query parameters' \
uv run uvicorn support_copilot.app:app --host 127.0.0.1 --port 8000
```

Filtering can remove necessary evidence. A filter matching nothing yields no passages and an insufficient-evidence response; it does not remove the filter as a fallback. The snapshot identifier is a documentation snapshot, not a claimed FastAPI software release. The normal evaluation preflight requires the dataset's exact snapshot.

After configuring `OPENAI_API_KEY`, prepare embeddings and compare fresh runs with identical K, prompt, corpus, labels, and judge settings:

```bash
uv run copilot embed
COPILOT_RETRIEVAL_MODE=vector uv run copilot eval run --split dev --output runs/phase4-vector-dev
COPILOT_RETRIEVAL_MODE=hybrid uv run copilot eval run --split dev --output runs/phase4-hybrid-dev
uv run copilot eval compare runs/phase4-vector-dev runs/phase4-hybrid-dev
uv run copilot eval adversarial-run --output runs/phase4-adversarial
```

These are paid commands. Each completed vector/hybrid case normally uses one query embedding, one generation, and one judge call. The adversarial suite normally uses twelve generation calls without embeddings/judges. SDK retries remain disabled, timeouts remain 45 seconds per call, and output limits remain configured. Full run artifacts preserve requested/returned model identifiers and reported tokens; verified dollar pricing is still unavailable.

Inspect failures and use `eval review-sample` / `eval review-record` from Phase 3 before selecting settings. Select using development quality, errors, latency, usage, and uncertainty. Only after choosing a configuration, run it with `--split test` and a fresh output directory, using the same explicit mode. Do not repeatedly adjust settings based on those ten held-out cases. If hybrid does not improve the relevant tradeoff, retain vector and report that result.

## 8. Checks and actual results

The saved [results report](results.md) distinguishes real SQL measurements, scripted checks, and blocked live work. Real keyword retrieval produced Recall@5 **0.6923** and MRR@5 **0.5962** over 13 answerable development cases. No answer-quality or vector/hybrid improvement has been measured.

The test suite covers RRF arithmetic, deterministic ties, duplicate handling, empty branches, indexed identifier search without embeddings, pre-ranking filters, migration with existing embeddings, generated-vector refresh, mode routing, streamed bodies without Content-Length, UTF-8 payload bounds, and adversarial metric denominators. It includes a scripted answer that follows an attack despite a valid citation, showing the boundary's limitation.

```bash
TEST_DATABASE_URL=postgresql://copilot:local-development-only@127.0.0.1:5433/copilot uv run --locked pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
git diff --check
```

Observed on 11 November 2026: **116 passed, 3 paid live tests skipped, 1 existing Starlette deprecation warning**, in 14.68 seconds. Ruff checks passed across 45 Python files. The 0.4.0 wheel and source distribution built successfully. PostgreSQL tests use isolated temporary schemas; mocked embeddings never populate the real corpus. An initial new test accidentally mutated shared fixture evidence; it was changed to use a deep copy, and the complete suite then passed. A live adversarial command was attempted and stopped with `Set OPENAI_API_KEY on the server to enable paid calls.` No live artifact or human-reviewed label was fabricated.

## 9. Decisions and tradeoffs

One PostgreSQL service handles both retrieval branches; there is no external search service. Generated search vectors make updates automatic and auditable, at the cost of extra storage and index maintenance. English normalization is a small, explicit starting point for this English corpus; it is not ideal for every code identifier. OR matching trades specificity for recall. Section weighting and RRF=60 are declared initial settings, not empirically optimized values.

Fusion avoids pretending cosine distance and keyword scores have comparable scales. It still adds a SQL query and a candidate-budget choice. Both branches currently run sequentially; actual latency tradeoffs must be measured. Exact cosine search is appropriate for 81 chunks and does not claim large-corpus scalability.

The original prompt and vector ranking remain available, while shared size limits now apply across modes. Fresh comparison runs under the same runtime isolate retrieval changes better than mixing historical runtime versions. The default stays vector because the missing credentials prevent a fair measured comparison. No extra reranker is justified by the evidence obtained so far.

## 10. Failure cases and limits

| Boundary | Implemented limit / remaining risk |
| --- | --- |
| Question | 1–4,000 characters after trimming; API validation rejects invalid input with 422, and direct pipeline calls validate too. |
| POST body | 16,384 bytes, counted from the stream even without Content-Length; over-limit requests return 413. This is not a slow-client or denial-of-service guarantee. |
| Generation data | 64,000 UTF-8 JSON bytes; over-limit evidence returns `context_too_large` before generation, without silently truncating code. It is a byte limit, not a token count. |
| Judge data | 128,000 UTF-8 JSON bytes; over-limit input becomes a separate judge failure with null scores. |
| Citation check | Rejects unknown IDs; URLs come from supplied passages. Supported meaning is still not guaranteed. |
| Attack signal | Checks named markers in completed output. Marker omission can miss an attack; a defensive quotation can trigger a false positive. Manual semantic inspection remains necessary. |
| Benign refusal | Non-answer statuses on four answerable controls, with an explicit eligible denominator. Application/provider errors are reported separately, not counted as safe answers. |

The adversarial suite has six attacks and six controls, all agent-inspected and zero user-reviewed. Its document attacks are controlled copies after retrieval, not a retrieval-attack benchmark. Some related passages outside the starter labels may be relevant; strict chunk recall can understate usefulness. No prompt, format constraint, or string check guarantees safety. The generator has no tools, so it cannot execute text or follow links; it can still produce misleading advice or malicious links in an answer.

The actual database retains 81 chunks with zero hosted embeddings. Vector/hybrid comparison, semantic attack inspection on live outputs, and real unnecessary-refusal rates remain pending credentials. These are explicit measurement gaps, not positive results.

## 11. Five interview questions

**Why not call keyword retrieval BM25?** The code uses PostgreSQL `ts_rank_cd` over weighted text-search vectors. It does not implement the BM25 formula or use a BM25 extension.

**Why fuse ranks instead of raw scores?** The branches have different scales and interpretations. RRF uses rank positions, rewarding agreement without assuming score calibration. Candidate depth and the fusion constant still affect results and need evaluation.

**Why keep vector as the default?** We measured keyword retrieval but could not run the hosted vector/hybrid comparison without credentials. Switching defaults on an unmeasured assumption would overstate the evidence.

**What guardrail failure can you demonstrate?** A scripted response can use a real citation ID while repeating an injected instruction's marker. Citation validation accepts it; the adversarial evaluator flags it. That proves a structural check cannot establish semantic support, not that a live model will fail at the scripted rate.

**How do you prevent a defensive system from refusing valid questions?** Include answerable benign controls such as legitimate authentication questions and quoted attack phrases. Measure non-answer outcomes separately from errors and inspect the text. No blanket attack-phrase filter is used here, and no real false-refusal rate has yet been measured.

## 12. Hands-on exercise

Open `keyword-dev.json`, find `ordinary-01`, and compare its labelled chunks with the five retrieved sections. Explain why matching “parameter” vocabulary is insufficient. Then manually compute RRF for lists `[a,b]` and `[b,c]` at constant 60 and compare your result with `tests/test_hybrid.py`.

Run the free adversarial validator and read one document attack alongside its benign source case. In `tests/evaluation/test_adversarial.py`, inspect the test where a valid citation accompanies a malicious marker. Identify which check succeeds, which semantic property remains unproven, and why the report must retain both observations. After adding credentials, inspect a real development and adversarial run before considering any retrieval-default change.
