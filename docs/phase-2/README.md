# Phase 2 — Baseline RAG with citations

## 1. What we built and why

We implemented the first question-answering pipeline: OpenAI embeddings, PostgreSQL vector retrieval, a structured generation call, and citations resolved against the exact retrieved chunks. It exposes `POST /ask` and two additional CLI commands: `embed` and `index-status`.

The baseline is deliberately simple enough to diagnose later. It performs exact vector-only retrieval, with a default top-k of five. We can inspect the passages separately from the model's answer. Every completed request records corpus/configuration/prompt identifiers, stage timings, provider-reported usage, and the selected outcome. This prepares the project for evaluation without claiming that evaluation exists already.

**Verification status:** 54 tests passed, including nine real PostgreSQL integration tests; three paid smoke tests were skipped. No OpenAI key is configured in this environment. Therefore embeddings and generation have been implemented and tested with scripted SDK responses, but live semantic retrieval, answer usefulness, and fallback quality have not been measured. The real saved corpus still has 81 chunks and zero embeddings.

## 2. What remains for later

Phase 3 will add reviewed datasets, retrieval/answer metrics, run artifacts, judge rubrics, and failure analysis. Phase 4 will compare keyword/hybrid retrieval and assess guardrails, prompt injection, input limits, and inappropriate refusals. Phase 5 will add the dashboard, deployment packaging, regression checks, and portfolio report.

There is no hybrid search, reranking, evaluation dataset, model judge, Streamlit application, authentication, or CI workflow in this phase. Citation membership checking is necessary for the Phase 2 response contract; citation support evaluation and adversarial testing remain separate work.

## 3. Concepts in plain language

**Embedding.** An embedding represents text as a list of numbers. The query and stored chunks must use the same embedding model and dimensions to make their distances meaningful. Identical dimensions alone do not make two models interchangeable.

**Vector retrieval.** PostgreSQL compares the query embedding with stored chunk embeddings and returns the nearest ones. We use cosine distance: lower means closer in vector space. It does not mean “probability that this answer is correct.” Exact search compares all eligible rows; with only 81 chunks there is no reason to introduce an approximate index yet.

**Retrieval-augmented generation.** The model receives the question and the selected text passages. It drafts an answer based on those passages. Retrieval and generation can fail independently: good passages can lead to a bad answer, and an otherwise capable model cannot recover evidence that was never supplied.

**Structured output.** The provider produces an object matching a defined schema. Local validation then checks relationships such as “an answered outcome needs text and at least one citation.” Valid structure does not establish factual accuracy.

**Citation validity versus support.** Validity means the cited chunk was actually retrieved. Support asks whether the chunk justifies the claim. We enforce membership now, using database URLs; we do not yet measure whether the cited text supports every statement.

**Trace.** A trace explains what happened during one request: the configuration, retrieved evidence, provider calls, timing, and reported tokens. It is diagnostic data, not a benchmark score.

## 4. Data and request flow, with an example

First run `copilot init-db`. It upgrades a Phase 1 database in one transaction, adding `chunk_embeddings` and changing the schema version from 1 to 2. Running it again does nothing destructive. Existing document/chunk IDs and hashes remain intact.

Next run `copilot embed` after configuring an API key. It selects only chunks lacking an embedding for the selected model, dimensions, and content hash. It submits batches of up to 16 texts to OpenAI. Each successful batch is checked for correct length, indexing, finite values, and nonzero vectors before being stored transactionally. The returned model name is retained with each row. If a later batch fails, earlier batches remain available and are reused on retry. A partially embedded corpus cannot serve answers.

For a question such as **“How do I require item_id to be an integer path parameter?”**, the request flow is:

1. Validate the request object and create a unique request ID.
2. Load the versioned settings and prompt, including model names and top-k.
3. Check that every chunk in the configured snapshot has a matching embedding.
4. Embed the question with the same embedding model and dimensions.
5. Order matching chunks by cosine distance, then chunk ID to break ties; take the first k.
6. Send their IDs, titles, section names, and contents alongside the question to the Responses API. The model returns an outcome, optional answer/clarification, brief reason, and citation IDs.
7. Require every cited ID to occur in the retrieved set. Attach URLs, titles, and sections from those records; do not accept a model-generated citation URL.
8. Return the result, passages, and trace. Log the request ID, outcome, count, and timing without logging the question, answer, passages, or API key.

The expected evidence is the saved Path Parameters documentation explaining `item_id: int`. That is an intended live smoke case, not an observed live retrieval result. Offline tests verify vector ordering using hand-constructed vectors and scripted provider behavior; they cannot prove that OpenAI will rank this evidence correctly.

## 5. Files and responsibilities

| File | Responsibility |
| --- | --- |
| `src/support_copilot/config/baseline-v1.json` | Preserved baseline parameters, corpus selection, batch size, timeout, and output budget. |
| `src/support_copilot/prompts/answer-v1.txt` | Evidence-only answer policy and instructions for the three outcomes. |
| `src/support_copilot/settings.py` | Validates settings, applies environment overrides, loads the prompt, computes the effective configuration hash, and reads the API key. |
| `src/support_copilot/contracts.py` | Request, structured draft, citations, passages, usage, trace, cost-unavailable, and final response models. |
| `src/support_copilot/provider.py` | Calls the official SDK, checks embedding output, extracts structured answers and usage, and maps provider failures to safe messages. |
| `src/support_copilot/retrieval.py` | Embedding coverage, resumable corpus indexing, and exact pgvector cosine retrieval. |
| `src/support_copilot/rag.py` | Coordinates the request stages, validates citation membership, and assembles responses and error traces. |
| `src/support_copilot/errors.py` | Small application exception carrying an HTTP code, safe message, error identifier, and optional trace. |
| `src/support_copilot/migrations/002_embeddings.sql` | Additive Phase 1 → Phase 2 migration with vector dimension/norm checks. |
| `src/support_copilot/db.py` | Initialization now applies migration 2; ingestion upserts unchanged chunks to preserve embeddings and removes obsolete chunks. |
| `src/support_copilot/app.py`, `cli.py` | `/ask` endpoint and `embed`/`index-status` CLI entry points. |
| `tests/test_provider.py`, `test_rag.py` | Real SDK parsing over a mock HTTP transport; contract, citation, timeout, quota/authentication, and fallback paths. |
| `tests/test_embeddings_database.py` | Migration, reuse, partial failure/resume, cosine order, stale hash/model exclusion, and HTTP/database integration. |
| `tests/test_live.py` | Three explicitly gated paid smoke cases. |
| `.env.example`, `pyproject.toml`, `uv.lock` | Safe environment example and locked official SDK dependency. |

The Phase 1 snapshot files were not modified. The root README now describes the implemented baseline, and the Phase 1 guide is labelled as a historical record.

## 6. Important functions and the response contract

`load_settings()` reads `baseline-v1.json` and applies only the documented environment overrides. `config_hash()` fingerprints the effective configuration. The prompt filename and its separate SHA-256 are recorded so editing prompt bytes remains observable even without renaming the file.

`embed()` calls `client.embeddings.create()` with explicit dimensions and floating-point output. It restores batch order using the provider's `index` fields and rejects missing, duplicate, zero, or malformed vectors. `embed_corpus()` writes completed batches and skips rows that already match. `corpus_status()` reports total and embedded chunks without making an API call. `retrieve()` uses parameterized SQL and pgvector's cosine operator with snapshot/model/dimension/content-hash constraints.

`generate()` calls `client.responses.parse(..., text_format=AnswerDraft)` with `store=False`, a reasoning effort of `low`, and a 4,096-token output budget. No tools, conversation memory, or external search are supplied. The budget includes reasoning and visible output. Refusals and incomplete responses are provider failures, not evidence-based abstentions.

`answer_question()` records stage timings and successfully parsed provider usage, then checks citation membership. `AnswerDraft.consistent_outcome()` enforces these rules:

| Outcome | `answer` | `clarification_question` | Citations |
| --- | --- | --- | --- |
| `answered` | Nonempty text | `null` | At least one valid retrieved chunk ID |
| `needs_clarification` | `null` | Nonempty focused question | Empty |
| `insufficient_evidence` | `null` | `null` | Empty |

All three outcomes are successful HTTP 200 responses and include a brief `reason`, `retrieved_passages`, and `trace`. Citations are in a separate `citations` array containing `chunk_id`, `source_url`, `title`, and `section`. They support the answer as a whole; this baseline does not align citations to individual sentences. Duplicate citation IDs are deduplicated in their original order.

The trace includes the request ID, pipeline/configuration identifiers, prompt hash/version, corpus ID/hash, embedding model/dimensions, requested generation model, top-k, reasoning effort, output limit, timings, and per-call usage. Each provider call records requested and returned model names and the provider request ID when available. The `X-Request-ID` HTTP header matches the response ID.

Usage preserves the provider's input, output, total, cached-input, and reasoning token fields where available. Reasoning tokens are already included in output tokens; cached tokens are part of input tokens. Do not add either subset again when computing totals. Indexing usage is reported separately by the CLI; an answer trace contains only its query embedding and generation calls.

Cost always reports `{"status":"unavailable","estimated_usd":null,...}` in this baseline because no verified pricing configuration has been enabled. There are no hardcoded rates or invented zero-cost results. A future configured estimator needs to account for the chosen model, cache behavior, service tier, and pricing date; token counts alone are not an invoice.

## 7. Setup, commands, and expected behavior

For an existing Phase 1 checkout:

```bash
uv sync --locked
docker compose up -d --wait
uv run copilot init-db
uv run copilot index-status
```

For a fresh checkout, first copy `.env.example` to `.env` and ingest the saved snapshot after initialization:

```bash
uv run copilot ingest --snapshot data/snapshots/fastapi-d4f83a093dd1b2ab
```

`init-db` reports schema version 2. Before indexing, the included corpus reports `chunks: 81`, `embedded_chunks: 0`, and `ready: false`. `/ready` can still be HTTP 200 because it checks database/schema readiness, not provider credentials or embedding coverage.

Set `OPENAI_API_KEY` in your local `.env` or process environment; do not commit it or paste it into chat. Existing `.env` files are preserved. The supported environment overrides are:

| Variable | Default |
| --- | --- |
| `COPILOT_GENERATION_MODEL` | `gpt-5.6-terra` |
| `COPILOT_EMBEDDING_MODEL` | `text-embedding-3-small` |
| `COPILOT_EMBEDDING_DIMENSIONS` | `1536` |
| `COPILOT_TOP_K` | `5` |

Top-k must be 1–20; dimensions must be 1–2,000 and supported by the selected embedding model. Model overrides must support the APIs and parameters this baseline uses. Changing the embedding model/dimensions requires a matching complete set of corpus embeddings. Changing only the answer model or top-k does not re-embed the corpus. Effective overrides alter the recorded configuration hash.

These commands make paid provider calls:

```bash
uv run copilot embed > /tmp/copilot-embedding-result.json
uv run copilot index-status
uv run uvicorn support_copilot.app:app --host 127.0.0.1 --port 8000
```

The initial embedding command processes the missing chunks in six batches of at most 16 for the included corpus. A successful run reports `embedded_chunks: 81`, `ready: true`; a repeat reports `new_embeddings: 0` and no provider calls. These are expected behaviors, not live results observed here. The redirection saves reported indexing usage for inspection; the application does not create an evaluation artifact store yet.

In another terminal:

```bash
curl -s http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"How do I require item_id to be an integer path parameter?"}'
```

Try the unrelated question “What is tomorrow's weather forecast for Delhi?” and the ambiguous question “How do I validate it?” Inspect `status`, `reason`, retrieved passages, and citations. The model is instructed to abstain or clarify appropriately, but a prompt does not guarantee that behavior.

Offline and database tests:

```bash
uv run pytest -m 'not integration and not live' -q
TEST_DATABASE_URL=postgresql://copilot:local-development-only@127.0.0.1:5433/copilot uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
```

Use your actual local database URL if changed. Integration tests create isolated schemas, use scripted embeddings, and clean up their schemas; they do not place fake embeddings into the real corpus. Without `TEST_DATABASE_URL` the nine database tests are skipped. Normal tests use HTTPX's mock transport, not a live provider.

After setting the key and running `copilot embed`, explicitly opt in to paid smoke tests:

```bash
RUN_LIVE_TESTS=1 uv run pytest -m live -q
```

The smoke suite makes three question-embedding calls and three generation calls if prerequisites and all stages succeed. It does not automatically embed the corpus. Each generation uses the configured output budget. Failures may still incur provider charges; automatic SDK retries are disabled. Selecting `-m live` alone does not opt in: `RUN_LIVE_TESTS=1` is required. These checks assert the three intended outcomes and valid citations, not full semantic correctness or a quality benchmark.

## 8. Actual checks and results

Observed on **9 November 2026** using Python 3.12.0, OpenAI SDK 2.54.0, and PostgreSQL 17 / pgvector 0.8.2:

| Check | Actual result |
| --- | --- |
| Complete deterministic suite with PostgreSQL | **54 passed, 3 paid tests skipped**; 45 offline tests and 9 database tests. |
| Static/style checks | Ruff check and format check passed. |
| Package verification | Wheel built successfully; it includes the versioned configuration, prompt, base schema, and migration, with no environment file. |
| Real Phase 1 database upgrade | Schema became version 2; original corpus remains 81 chunks. |
| Real embedding coverage | **0 / 81**, because no API key is configured. |
| Temporary Uvicorn server | `/health` and `/ready` returned 200; `/ask` with key explicitly disabled returned 503 `missing_api_key` and a matching request-ID header. |
| Model SDK tests | Actual SDK requests/parsing exercised with scripted HTTP responses; no paid calls. |
| Migration test | Existing chunk IDs/hashes survived upgrade; a second initialization succeeded. |
| Embedding reuse | A 12-chunk synthetic corpus was embedded in three batches, re-ingested, then indexed with zero additional provider calls and unchanged vectors. |
| Partial failure | Failure after the first five synthetic embeddings left 5 / 12 stored and readiness false; retry embedded only the remaining seven. |
| Cosine ordering | Database distances matched hand-calculated 0, approximately 0.292893, and 1; incompatible models/dimensions were excluded. |
| Error handling | Tests covered malformed outputs, unknown citations, authentication, rate/quota limits, server failures, and timeout without retries or provider-message leakage. |
| Live semantic retrieval/generation | **Not run: missing `OPENAI_API_KEY`.** No benchmark or live outcome is claimed. |

The existing upstream Starlette TestClient warning about its deprecated HTTPX integration remains visible; it is not suppressed. It does not fail the tests. Offline success cannot establish production reliability, model safety, answer correctness, or an improvement over a measured baseline.

## 9. Decisions, alternatives, and tradeoffs

**Provider and model choice.** We use one provider and its official Python SDK. The current documentation lists `gpt-5.6-terra` with Responses and structured-output support, and `text-embedding-3-small` with a default 1,536-dimensional embedding. We selected a configurable generation model rather than inventing a dated snapshot ID; the current Terra page exposes the alias. Responses record returned model names, but aliases can drift and cannot guarantee fixed weights. Account access remains unverified without a key. Sources: [generation model](https://developers.openai.com/api/docs/models/gpt-5.6-terra), [embedding guide](https://developers.openai.com/api/docs/guides/embeddings).

**API shape.** We use the documented `responses.parse()` Pydantic integration and `embeddings.create()` API. `low` reasoning is supported by the selected generation model. Structured output gives a reliable object shape when the model completes successfully; local checks enforce outcome consistency and citation membership. Sources: [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [reasoning](https://developers.openai.com/api/docs/guides/reasoning).

**Exact vector baseline.** We use cosine distance and deterministic ID tie-breaking. There is no approximate-index tuning or extra retrieval signal to complicate later comparisons. The corpus snapshot restriction selects the intended baseline corpus; this is not the user-facing metadata-filter feature planned for Phase 4. pgvector accepts the serialized vector as a bound parameter cast to `public.vector`; SQL strings never interpolate user text. Source: [pgvector](https://github.com/pgvector/pgvector).

**Separate embedding table.** The primary key is `(chunk_id, model, dimensions)` with content-hash checks. Different embedding configurations can coexist without mixing their vector spaces. Vectors have an explicit dimensionality check and nonzero norm. This avoids rewriting the Phase 1 chunk record or changing its ID.

**Preserve embeddings on ingestion.** Phase 1 replaced every chunk row. With an embedding foreign key, that would cascade-delete paid work. Phase 2 now removes obsolete chunks and upserts the expected ones, preserving unchanged IDs and their vectors. The content hash still determines whether an embedding can be used. The importer remains idempotent.

**Resumable batches.** Network calls run outside a database transaction; completed batches are committed individually. A concurrent change is checked before writing, using the same advisory write lock as ingestion. Concurrent indexers may still both pay to embed the same pending chunk before storing it; storage remains unique. There is no background worker or distributed job lock.

**No calibrated threshold.** Top-k will often return something even for an unrelated question. We do not interpret a distance cutoff as certainty. The model decides whether evidence is useful, ambiguous, or insufficient using the prompt. That decision can be wrong. A truly empty result skips generation and returns insufficient evidence; a missing/partial index is an operational error instead of an abstention.

**No price estimates yet.** This phase records actual returned token usage and explicitly unavailable cost. Verified per-model, per-tier pricing configuration has not been enabled. This avoids presenting undocumented assumptions as dollar measurements.

## 10. Failure cases and limitations

| HTTP status / code | Meaning |
| --- | --- |
| 422 | Invalid request shape, including an empty/whitespace question. |
| 503 `missing_api_key` | Configure a server-side API key. |
| 503 `corpus_not_ready` | Run ingestion/indexing; the selected corpus lacks complete matching embeddings. |
| 503 `database_unavailable` | Database query failed; check service and schema initialization. |
| 503 `provider_authentication` | Provider rejected configured credentials. |
| 503 `provider_rate_limit` | Provider rate or billing/quota limit. |
| 504 `provider_timeout` | Provider request timed out. |
| 502 `provider_error` | Other provider failure, such as an unsupported model parameter. |
| 502 `invalid_citation` / `invalid_provider_output` | The returned draft violates the response contract. |
| 502 `provider_incomplete` / `provider_refusal_or_empty_output` | No complete structured answer was returned. |

Errors contain a safe code/message, request ID, and a trace when the pipeline reached trace initialization. Configuration failures before that point have `trace: null`. Raw provider error bodies and exception strings are not returned. Successful earlier calls remain in error traces; when the SDK raises before returning a parsed object, usage for that failed call is unavailable and may still have been billed. Total timing covers the pipeline, not client/network transit or HTTP serialization.

The provider timeout is per SDK operation, not a global request deadline. SDK retries are disabled so a single request does not silently add repeated paid attempts. Model availability, network access, quotas, and parameter compatibility can still fail. `store=False` disables Responses storage for this request; it is not a claim about all provider retention policies.

The prompt treats evidence as data, but prompt instructions are not a safety guarantee. Citation checks do not detect unsupported claims, contradictory evidence, malicious text, or invented links embedded in free-form answers. The model's brief `reason` is also unscored text. Input size limits and adversarial tests belong to Phase 4. Current top-k and output settings have not been tuned or selected through evaluation.

The public-document snapshot is incomplete and not tied to a named FastAPI release. The model may abstain unnecessarily or answer outside the evidence. The pipeline has no authentication, conversation memory, load test, connection pool, user interface, or production-deployment claim. The three live smoke assertions are intentionally small and cannot substitute for Phase 3's dataset and metrics.

## 11. Five likely interview questions

**Why keep retrieval vector-only initially?**

It gives me a clear reference pipeline. Before adding keyword retrieval or reranking I want to observe whether failures come from retrieval or generation and compare changes on the same cases. I have not yet measured that hybrid search would help.

**How do you know the cited source is real?**

The model can only select chunk IDs. I require each selected ID to belong to the retrieved set and resolve the source URL from the database. That proves citation membership, not that the source supports every claim. Support requires separate evaluation.

**Why is cosine distance not confidence?**

It measures relative position in an embedding space. Even an unrelated query has nearest neighbors. Without labelled evaluation and calibration, a numeric threshold cannot tell me the probability that an answer is correct. This baseline relies on an explicit model abstention policy with acknowledged limitations.

**How do you avoid paying to re-embed unchanged documents?**

Embeddings are keyed by chunk, model, and dimensions and carry the content hash. The indexing query skips matching rows; successful batches survive failures. Re-ingestion preserves unchanged chunk rows and their embeddings. A model/dimension change needs a separate matching index.

**What did you actually test, and what remains unknown?**

I ran 54 deterministic tests, including real PostgreSQL vector and migration behavior, and HTTP checks against a running local API. The SDK was exercised with scripted HTTP responses. Three live checks were skipped because no API key was configured. I cannot claim live answer quality, semantic retrieval recall, latency, cost, or model safety yet.

## 12. Hands-on exercise

1. Run `copilot index-status` before embedding. Explain why `/ready` can return 200 while the index says `ready: false`.
2. After configuring your key, run `copilot embed` twice. Inspect the JSON results: the second should have `new_embeddings: 0` and an empty `provider_calls` array. Re-ingest the snapshot and confirm the embedded count remains 81.
3. Ask the integer-parameter question. Match each citation ID to a retrieved passage and read the actual supporting text. Decide whether the answer is supported; the membership check alone cannot do this for you.
4. Restart the API with `COPILOT_TOP_K=1`, ask the same question, and compare the passages and configuration hash. Do not label one better from a single example.
5. Try the unrelated and ambiguous questions. Record the outcomes you actually observe, including failures. These observations can inform Phase 3 case design; they are not benchmark results yet.

Stop after this phase. Phase 3 begins only when explicitly requested.
