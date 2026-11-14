# Evaluation-Driven Technical Support Copilot

A portfolio project for answering FastAPI support questions from documented evidence. Its evaluation workflow compares pipeline runs and exposes failures, quality, latency, and provider-reported usage. Dollar cost is reported as unavailable until verified pricing is configured.

**Current status: Phase 5 implemented; live comparisons pending.** The copilot includes a Streamlit question interface and evaluation dashboard, saved-run regression gates, GitHub Actions, and container packaging. It supports vector, PostgreSQL keyword, and RRF hybrid retrieval, metadata filters, bounded inputs, and adversarial evaluation. The 30-case quality dataset and 12 attack/control cases are agent-inspected, with zero user-reviewed labels. Keyword retrieval has been measured locally; live vector/hybrid improvement and guardrail effectiveness remain unmeasured. Vector remains the default.

## Current architecture

```text
Six official FastAPI pages + MIT license
              │ fetch-docs (network required)
              ▼
Saved HTML + checksummed manifest
              │ ingest (offline extraction and deterministic chunking)
              ▼
PostgreSQL: documents ──< chunks
                           │ copilot embed → OpenAI embeddings
                           ▼
                    chunk_embeddings (pgvector)
                           ▲ vector / keyword / RRF hybrid retrieval
Streamlit Ask → POST /ask → input limits → retrieval + filters → OpenAI structured answer
                                                     │
                                    citation ID checks → answer + sources + trace

Versioned cases → eval run → same baseline + separate LLM judge
                              │
                              ▼
                  JSONL case records + metric summaries
                              │
            Streamlit dashboard / compare / regression gate / review
```

PostgreSQL runs in Docker Compose. Python runs locally with uv or in the optional application containers. `/health` checks the API process; `/ready` checks database/schema availability. `copilot index-status` reports embedding coverage and readiness for the configured mode. Vector/hybrid require complete embeddings; keyword retrieval does not. No reranker is implemented.

## Run locally

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/), and running Docker with Compose. `.python-version` selects Python 3.12, the version used for verification.

```bash
uv sync --locked
cp .env.example .env
docker compose up -d --wait
uv run copilot init-db
uv run copilot ingest --snapshot data/snapshots/fastapi-d4f83a093dd1b2ab
uv run copilot index-status
```

Existing users should run `uv sync --locked` and `uv run copilot init-db` to apply schema version 3, adding a generated text-search column and GIN index. Migrations preserve corpus IDs, text, and embeddings. Copy `.env.example` only on first setup; preserve an existing `.env`.

Add your `OPENAI_API_KEY` to `.env` locally. The next command makes paid embedding calls; completed batches are reused on subsequent runs:

```bash
uv run copilot embed
uv run uvicorn support_copilot.app:app --host 127.0.0.1 --port 8000
```

The included database password is for this localhost development service only. If you change it or the port, update both the Compose variables and `DATABASE_URL`. PostgreSQL initialization credentials apply when its data volume is first created.

In another terminal:

```bash
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/ready
curl -s http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"How do I require item_id to be an integer path parameter?"}'
uv run pytest -m 'not integration and not live' -q
uv run ruff check src tests
uv run ruff format --check src tests
```

Health/readiness return HTTP 200 when initialized. `/ask` requires a key and a ready corpus for its mode; otherwise it returns an explicit 503 error. A successful request returns `answered`, `needs_clarification`, or `insufficient_evidence`, alongside retrieved passages and a trace. Interactive API docs: <http://127.0.0.1:8000/docs>. The saved snapshot contains **6 documents and 81 chunks**; re-ingestion preserves IDs and embeddings.

Run all tests against the local database using isolated temporary schemas:

```bash
TEST_DATABASE_URL=postgresql://copilot:local-development-only@127.0.0.1:5433/copilot uv run pytest -q
```

Use your actual local connection string if changed. Without `TEST_DATABASE_URL`, database tests are explicitly skipped. Normal tests never make paid calls or download documentation. After embedding the corpus, opt in to three paid smoke cases with `RUN_LIVE_TESTS=1 uv run pytest -m live -q`. These check live behavior; they are not an evaluation benchmark.

Optional: capture a new six-page snapshot with `uv run copilot fetch-docs`. It prints the new directory to pass to `ingest --snapshot`. This may produce different bytes and IDs as upstream changes; use the included directory to reproduce this phase. Stop the database with `docker compose stop`; its volume persists.

## Five phases

1. **Complete:** [Foundation and document ingestion](docs/phase-1/README.md).
2. **Implemented, live checks pending:** [Baseline RAG with citations](docs/phase-2/README.md).
3. **Implemented, live benchmark pending:** [Evaluation harness and failure analysis](docs/phase-3/README.md).
4. **Implemented, live comparisons pending:** [Retrieval improvements and guardrail experiments](docs/phase-4/README.md).
5. **Implemented:** [Interface, regression checks, and delivery](docs/phase-5/README.md), with a [portfolio report](docs/phase-5/results.md).

Only implemented phases have guides. The provider is OpenAI using its official SDK. Defaults are `text-embedding-3-small` (1,536 dimensions) and `gpt-5.6-terra`, verified against official documentation on 9 November 2026. Models and top-k can be overridden in `.env`; the packaged `baseline-v1.json` and `answer-v1.txt` preserve the baseline defaults and prompt. See Phase 2 for citations and configuration details.

## Evaluate and inspect

Start the question interface in another terminal after launching the API:

```bash
uv run copilot-ui
```

Open <http://127.0.0.1:8501>. The **Evaluation** workspace browses completed runs under `runs/` without API, database, or model calls. It shows metric coverage, failures, latency, token usage, case details, and matched comparisons. The [Phase 5 guide](docs/phase-5/README.md) covers configuration, CI, and container setup.

The included dataset has 20 development and 10 held-out cases covering ordinary questions, exact identifiers, ambiguity, and missing evidence. Validate it without a key or database:

```bash
uv run copilot eval validate
```

After configuring a key and embedding the corpus, run paid evaluation and prepare a review packet:

```bash
uv run copilot eval run --split dev --limit 2 --output runs/dev-smoke
uv run copilot eval run --split dev --output runs/baseline-dev
uv run copilot eval review-sample --run runs/baseline-dev --output runs/review.json
```

Use a fresh output directory for each run. Artifacts retain dataset/corpus/config/prompt/model identities, evidence, answers, errors, timings, tokens, and scores. Metrics include chunk Recall@K, MRR, outcome accuracy, citation validity, and judge-assessed correctness, faithfulness, citation support, and response appropriateness. Judge failures and usage remain separate from application quality and usage.

Gate a candidate against a matched saved baseline (no model calls; exits 1 on regression):

```bash
uv run copilot eval check runs/baseline-dev runs/candidate-dev --max-drop 0.02
```

The [Phase 3 guide](docs/phase-3/README.md) explains formulas, comparison commands, review recording, and missing-score coverage. The [dataset guide](data/evaluation/fastapi-support-v1/README.md) explains label provenance and expansion toward 100 reviewed cases. Use development cases for choosing settings and reserve the test split for evaluation after those choices.

Measure keyword retrieval without model calls, or validate the separate adversarial cases:

```bash
COPILOT_RETRIEVAL_MODE=keyword uv run copilot eval keyword --report runs/keyword-dev.json
uv run copilot eval adversarial-validate
```

Use `COPILOT_RETRIEVAL_MODE=hybrid` to opt into RRF retrieval. Snapshot and exact section filters are configurable through `COPILOT_SNAPSHOT_ID` and `COPILOT_SECTION_FILTER`. The [Phase 4 guide](docs/phase-4/README.md) provides matched vector/hybrid run commands, controlled document-injection experiments, and the development-to-held-out selection workflow.

## Evidence and limitations

Verified on 14 November 2026: **143 tests passed; 3 paid live tests skipped**, including PostgreSQL integration tests and the keyword development regression. Ruff and package-build checks passed. The [keyword results](docs/phase-4/results.md) report Recall@5 **0.6923** and MRR@5 **0.5962** over 13 answerable development cases, with no model calls. These measure keyword retrieval only. Scripted provider tests do not establish live answer quality or safety. The existing Starlette TestClient deprecation warning remains documented. See the [Phase 5 verification record](docs/phase-5/results.md) for delivery checks.

This is a local public-document prototype. The corpus is a six-page website snapshot, not a named FastAPI release or complete documentation set. Byte/character limits bound requests but do not guarantee safety or token counts. Citation membership is deterministic; semantic support uses a fallible judge. A structurally valid answer can still follow an injection. Labels may miss alternative supporting chunks; the small held-out split is visible to the author. Hosted-model cost estimates remain unavailable. Container packaging does not add authentication or constitute a public production deployment.

Source URLs and hashes are in the [snapshot manifest](data/snapshots/fastapi-d4f83a093dd1b2ab/manifest.json). FastAPI documentation is attributed to Sebastián Ramírez and distributed with its downloaded [MIT license](data/snapshots/fastapi-d4f83a093dd1b2ab/LICENSE). The saved source remains separate from the project's implementation.
