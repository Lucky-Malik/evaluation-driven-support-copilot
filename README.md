# Evaluation-Driven Technical Support Copilot

A portfolio project for answering FastAPI support questions from documented evidence. The planned centerpiece is an evaluation workflow that compares pipeline versions and exposes failures, quality, latency, and estimated cost.

**Current status: Phase 1 complete.** The API and documentation ingestion work. No embeddings, search, generated answers, LLM calls, evaluation scores, or dashboard exist yet.

## Current architecture

```text
Six official FastAPI pages + MIT license
              │ fetch-docs (network required)
              ▼
Saved HTML + checksummed manifest
              │ ingest (offline extraction and deterministic chunking)
              ▼
PostgreSQL: documents ──< chunks
              ▲
FastAPI /ready checks connection, schema, and pgvector
FastAPI /health checks only that the API responds
```

PostgreSQL runs in Docker Compose. Python runs locally with uv. The vector extension is enabled, but no vector columns or search have been implemented.

## Run locally

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/), and running Docker with Compose. `.python-version` selects Python 3.12, the version used for verification.

```bash
uv sync --locked
cp .env.example .env
docker compose up -d --wait
uv run copilot init-db
uv run copilot ingest --snapshot data/snapshots/fastapi-d4f83a093dd1b2ab
uv run uvicorn support_copilot.app:app --host 127.0.0.1 --port 8000
```

Copy `.env.example` only on first setup; preserve an existing `.env`. The included password is for this localhost development database only. If you change it or the port, update both the Compose variables and `DATABASE_URL`. PostgreSQL initialization credentials apply when its data volume is first created.

In another terminal:

```bash
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/ready
uv run pytest -m 'not integration' -q
uv run ruff check src tests
uv run ruff format --check src tests
```

Both endpoints return HTTP 200 when initialized; `/ready` returns 503 if the database is unavailable or its schema is missing. Interactive API docs: <http://127.0.0.1:8000/docs>. Ingestion reports **6 documents and 81 chunks** for the saved snapshot; repeating it preserves IDs and row counts.

Run all tests against the local database using isolated temporary schemas:

```bash
TEST_DATABASE_URL=postgresql://copilot:local-development-only@127.0.0.1:5433/copilot uv run pytest -q
```

Use your actual local connection string if changed. Without `TEST_DATABASE_URL`, database tests are explicitly skipped. Tests never make paid calls or download documentation.

Optional: capture a new six-page snapshot with `uv run copilot fetch-docs`. It prints the new directory to pass to `ingest --snapshot`. This may produce different bytes and IDs as upstream changes; use the included directory to reproduce this phase. Stop the database with `docker compose stop`; its volume persists.

## Five phases

1. **Complete:** [Foundation and document ingestion](docs/phase-1/README.md).
2. Planned: baseline vector retrieval and cited answers.
3. Planned: evaluation harness, reviewed datasets, and failure analysis.
4. Planned: keyword/hybrid retrieval and guardrail experiments.
5. Planned: dashboard, regression checks, and portfolio delivery.

Only the implemented phase has documentation. Provider and configurable model selection belong to Phase 2, after checking current official documentation.

## Evidence and limitations

Verified on 9 November 2026: **24 tests passed**, Ruff checks passed, live health/readiness succeeded, database outage returned 503 readiness, and repeated real-corpus ingestion preserved all records. The test suite reports one upstream Starlette deprecation warning about HTTPX TestClient support. See the phase guide for details.

This is a local public-document prototype, not a deployed support service. The corpus is a six-page website snapshot, not a named FastAPI release or complete documentation set. Chunk sizes are a soft character target, not a token limit. Images and linked pages are not downloaded. No claim about LLM quality is possible yet.

Source URLs and hashes are in the [snapshot manifest](data/snapshots/fastapi-d4f83a093dd1b2ab/manifest.json). FastAPI documentation is attributed to Sebastián Ramírez and distributed with its downloaded [MIT license](data/snapshots/fastapi-d4f83a093dd1b2ab/LICENSE). The saved source remains separate from the project's implementation.
