# Phase 5 — Interface, regression checks, and delivery

Phase 5 adds a Streamlit question interface and evaluation dashboard, a saved-run regression gate, GitHub Actions, and a container image for both the API and UI. The [portfolio report](results.md) distinguishes implementation evidence from model-quality evidence.

## Run the interface

From the repository root, after the setup in the root README:

```bash
uv sync --locked
uv run uvicorn support_copilot.app:app --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
uv run copilot-ui
```

Open <http://127.0.0.1:8501>. `copilot-ui` locates the app inside the installed package, including a wheel. Streamlit options can follow the command, for example `--server.port=8502`. It binds to loopback and disables usage telemetry by default.

**Ask:** submit a question of up to 4,000 characters. Only form submission calls the API; browsing and rerendering do not repeat paid requests. Answers, clarification requests, and insufficient-evidence outcomes have distinct displays. Open cited sources or expand passages and the trace to inspect evidence, timing, and provider-reported tokens. Questions are independent; include earlier details when answering a clarification. The most recent result is session-local, and a failed new submission clears it. No conversation is saved by the UI.

**Evaluation:** reads immediate subdirectories of `COPILOT_RUNS_DIR` (default `runs`). Each needs `run.json` and `cases.jsonl` from `copilot eval run`. No key, database, or API is needed to browse existing artifacts. An empty directory shows instructions rather than invented results. Interrupted, corrupt, and other artifact kinds are rejected. Summaries are recomputed from checksum-verified records. Inspect score coverage, categories, failures, individual evidence/answers/judge rationales, separate application and judge usage, and run identities. Download a summary or compare a matched candidate.

The dashboard supports completed **quality evaluations**. Keyword and adversarial reports retain their existing CLI workflows. Checksums detect accidental changes; local artifacts are not signed attestations. Keep the UI private because artifacts contain questions and answers.

| Server-side variable | Default | Purpose |
| --- | --- | --- |
| `COPILOT_API_URL` | `http://127.0.0.1:8000` | API base URL used by the Streamlit server |
| `COPILOT_RUNS_DIR` | `runs` | Directory of saved quality runs |

Variables load from the environment or `.env`. Retrieval/model settings remain on the API, preserving `/ask`. No keys are entered in the browser. The UI waits up to 120 seconds per HTTP read and does not automatically retry a timed-out submission, which may already have incurred model usage.

## Regression checks

Compare completed evaluations without new model calls:

```bash
uv run copilot eval check runs/baseline-dev runs/candidate-dev
uv run copilot eval check runs/baseline-dev runs/candidate-dev \
  --max-drop 0.02 --max-latency-ratio 1.5
```

The command prints JSON and exits **0** for a pass or **1** for a failed gate or invalid input. Runs must match dataset, corpus, split, case order, metric version, **K**, judge configuration, and judge prompt. Application settings may differ for retrieval experiments.

Default policy: no normalized metric may drop by more than 0.02 absolute points; the candidate must retain every baseline-scored case for each metric; application errors, judge failures, and skipped judgments may not increase. The baseline needs at least one score for every metric, so use a representative run containing answered cases. Missing judge scores cannot produce a passing gate. Optional latency gating compares application p95 against the baseline; it is off by default because timing is noisy. These are engineering thresholds, not statistical significance or safety tests.

Select settings using development runs, then freeze the configuration before held-out evaluation. Neither CI nor the UI launches paid evaluation automatically.

## CI

`.github/workflows/ci.yml` runs on pushes and pull requests with read-only repository permissions. It installs locked dependencies using Python 3.12 and uv 0.13.7, starts PostgreSQL 17 with pgvector, runs Ruff and all non-live tests, validates both datasets, builds Python distributions, and builds/smoke-tests the image. No provider credentials are required.

The free keyword development regression uses the pinned six-page corpus and requires Recall@5 ≥ 0.69 and MRR@5 ≥ 0.59, based on the recorded Phase 4 result of 0.6923 / 0.5962. UI tests use Streamlit AppTest; provider tests use scripted responses. CI does not establish live model quality or injection resistance. Hosted workflow execution happens after pushing the repository and is separate from local verification.

## Containers

The image installs locked runtime dependencies, includes the pinned corpus/datasets, excludes `.env` and local runs, and runs as an unprivileged user. API and UI use separate containers from the same image. The UI receives no provider key or database credentials. Only localhost ports are published.

Preserve your existing `.env`. From the repository root:

```bash
mkdir -p runs
# Match the bind-mounted runs directory owner, especially on Linux.
export COPILOT_UID=$(id -u)
export COPILOT_GID=$(id -g)
docker compose -f compose.yaml -f compose.app.yaml build
docker compose up -d --wait db
docker compose -f compose.yaml -f compose.app.yaml run --rm api copilot init-db
docker compose -f compose.yaml -f compose.app.yaml run --rm api \
  copilot ingest --snapshot data/snapshots/fastapi-d4f83a093dd1b2ab
```

Set `OPENAI_API_KEY` in `.env`. Vector/hybrid retrieval needs embeddings; this command makes paid calls:

```bash
docker compose -f compose.yaml -f compose.app.yaml run --rm api copilot embed
docker compose -f compose.yaml -f compose.app.yaml up -d --wait
```

For keyword mode, set `COPILOT_RETRIEVAL_MODE=keyword` and skip embedding; answering still needs a provider key. The UI can start alone to browse saved artifacts:

```bash
docker compose -f compose.yaml -f compose.app.yaml up -d --wait ui
```

API: <http://127.0.0.1:8000/docs>. UI: <http://127.0.0.1:8501>. `/ready` checks database/schema availability; use `copilot index-status` to inspect embedding coverage. To save a paid evaluation to the shared runs directory:

```bash
docker compose -f compose.yaml -f compose.app.yaml run --rm api \
  copilot eval run --split dev --output runs/candidate-dev
```

Always use a fresh output directory. Stop with `docker compose -f compose.yaml -f compose.app.yaml stop`; database and run files persist. Container connections use `db:5432`; local Python uses the host URI. URL-encode reserved characters when changing credentials in a connection URI.

This is private, single-user packaging. Public hosting still needs authentication, TLS, artifact access controls, rate/cost controls, secret management, backups, and monitoring. No hosted deployment is claimed.

## Implementation references

- [Streamlit CLI](https://docs.streamlit.io/develop/api-reference/cli/run) and [AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest).
- [uv in Docker](https://docs.astral.sh/uv/guides/integration/docker/) and [uv in GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/).
