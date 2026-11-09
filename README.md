# Evaluation-Driven Technical Support Copilot

A portfolio project for answering FastAPI support questions from documented evidence. The planned centerpiece is an evaluation workflow that compares pipeline versions and exposes failures, quality, latency, and estimated cost.

**Current status: Phase 2 implemented; offline and PostgreSQL checks passed.** The vector-only baseline includes embeddings, retrieval, structured answers, citations, and request traces. Live provider checks are pending because no OpenAI API key is configured. There are no evaluation scores or dashboard yet.

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
                           ▲ cosine-distance top-k
POST /ask → question embedding → retrieved passages → OpenAI structured answer
                                                     │
                                    citation ID checks → answer + sources + trace
```

PostgreSQL runs in Docker Compose. Python runs locally with uv. `/health` checks the API process; `/ready` checks database/schema availability. `copilot index-status` separately checks embedding coverage. The baseline uses exact cosine search, with no keyword search, hybrid retrieval, or reranking.

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

Existing Phase 1 users should run `uv sync --locked` and `uv run copilot init-db` to apply schema version 2. The migration preserves the corpus. Copy `.env.example` only on first setup; preserve an existing `.env`.

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

Health/readiness return HTTP 200 when initialized. `/ask` requires a key and all chunks embedded; otherwise it returns an explicit 503 error. A successful request returns `answered`, `needs_clarification`, or `insufficient_evidence`, alongside retrieved passages and a trace. Interactive API docs: <http://127.0.0.1:8000/docs>. The saved snapshot contains **6 documents and 81 chunks**; re-ingestion preserves IDs and embeddings.

Run all tests against the local database using isolated temporary schemas:

```bash
TEST_DATABASE_URL=postgresql://copilot:local-development-only@127.0.0.1:5433/copilot uv run pytest -q
```

Use your actual local connection string if changed. Without `TEST_DATABASE_URL`, database tests are explicitly skipped. Normal tests never make paid calls or download documentation. After embedding the corpus, opt in to three paid smoke cases with `RUN_LIVE_TESTS=1 uv run pytest -m live -q`. These check live behavior; they are not an evaluation benchmark.

Optional: capture a new six-page snapshot with `uv run copilot fetch-docs`. It prints the new directory to pass to `ingest --snapshot`. This may produce different bytes and IDs as upstream changes; use the included directory to reproduce this phase. Stop the database with `docker compose stop`; its volume persists.

## Five phases

1. **Complete:** [Foundation and document ingestion](docs/phase-1/README.md).
2. **Implemented, live checks pending:** [Baseline RAG with citations](docs/phase-2/README.md).
3. Planned: evaluation harness, reviewed datasets, and failure analysis.
4. Planned: keyword/hybrid retrieval and guardrail experiments.
5. Planned: dashboard, regression checks, and portfolio delivery.

Only implemented phases have guides. The provider is OpenAI using its official SDK. Defaults are `text-embedding-3-small` (1,536 dimensions) and `gpt-5.6-terra`, verified against official documentation on 9 November 2026. Models and top-k can be overridden in `.env`; the packaged `baseline-v1.json` and `answer-v1.txt` preserve the baseline defaults and prompt. See Phase 2 for citations and configuration details.

## Evidence and limitations

Verified on 9 November 2026: **54 tests passed; 3 paid smoke tests skipped**. Ruff checks passed. The actual database is migrated with **81 chunks and zero embeddings**; no paid calls were made. Local HTTP checks verified health/readiness and the missing-key error. Provider-dependent tests use the real SDK with scripted HTTP responses; they do not establish semantic retrieval or answer quality. The existing Starlette TestClient deprecation warning remains documented.

This is a local public-document prototype, not a deployed support service. The corpus is a six-page website snapshot, not a named FastAPI release or complete documentation set. Chunk sizes are a soft character target, not a token limit. Citation membership is checked; whether a passage actually supports a claim is not yet scored. Distance is not confidence. Estimated cost is explicitly unavailable because no verified pricing configuration is enabled. No claim about live LLM quality is possible yet.

Source URLs and hashes are in the [snapshot manifest](data/snapshots/fastapi-d4f83a093dd1b2ab/manifest.json). FastAPI documentation is attributed to Sebastián Ramírez and distributed with its downloaded [MIT license](data/snapshots/fastapi-d4f83a093dd1b2ab/LICENSE). The saved source remains separate from the project's implementation.
