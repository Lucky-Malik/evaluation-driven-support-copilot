# Phase 1 — Foundation and document ingestion

This is the historical Phase 1 implementation record. [Phase 2](../phase-2/README.md) now upgrades the schema to version 2 and preserves unchanged chunk rows during re-ingestion so their embeddings survive. Use the root README for current setup; the Phase 1 measurements below remain historical results.

## 1. What we built and why

We built a local FastAPI application, a PostgreSQL service with pgvector installed, an explicit schema initialization command, and a reproducible documentation ingestion pipeline. No external credentials or paid model calls are needed.

Later evaluation needs stable evidence. If the corpus changes between experiments, an apparent improvement might come from different documentation rather than a better pipeline. This phase preserves raw source bytes, their provenance, normalized text, and stable chunk identities so later runs can identify their evidence precisely.

The workspace started empty, without Git metadata or applicable `AGENTS.md` instructions. We selected uv and retained its generated lockfile. This phase creates project files; it does not create commits or a remote repository.

## 2. Intentionally left for later

Phase 2 will choose one hosted provider using its current official documentation and add configurable models, embeddings, vector-only retrieval, cited answers, clarification/insufficient-evidence outcomes, timing, and token accounting. No provider SDK or key placeholder is needed now.

Phase 3 adds the evaluation dataset, harness, judges, metrics, and review process. Phase 4 considers PostgreSQL full-text keyword search, hybrid retrieval, and measured guardrails. Phase 5 adds Streamlit, packaging, GitHub Actions, regression checks, and portfolio delivery. We have created no placeholder modules, schemas, or phase READMEs for these features.

## 3. Concepts in plain language

**Liveness versus readiness.** `/health` means the API process can respond. `/ready` means it can connect to PostgreSQL, find schema version 1 and the expected tables, and find the `vector` extension. An empty but initialized database is ready: readiness does not claim that a corpus has been ingested.

**Snapshot and provenance.** A snapshot is a saved collection of source bytes. Provenance records where those bytes came from. Our manifest records each official URL, title, filename, raw SHA-256 checksum, capture time, upstream attribution, and license checksum. The snapshot is identified by content, not by the current date or a guessed FastAPI release.

**Hash and stable ID.** SHA-256 turns bytes into a repeatable fingerprint. A checksum detects accidental changes; it is not a signature proving authenticity. Anyone able to edit all the files and manifest could recompute hashes. Source provenance comes from the observed HTTPS download and retained attribution.

**Chunk.** A chunk is a smaller piece of a document that a future retriever can return. Here it contains a heading path and one or more complete content blocks. It has no embedding yet.

**Idempotence.** Applying ingestion twice leaves the same records as applying it once. It is a property of the final database state, not a claim that the second run performs no work.

**Transaction.** All six documents and their chunks are written as one database transaction. If any write fails, PostgreSQL rolls back the entire import. An advisory transaction lock serializes this application's ingestions so two writers cannot interleave chunk replacement.

## 4. Data and request flow

`copilot fetch-docs` requests exactly six selected pages and the upstream license. It does not follow page links, download images, or crawl the website. Each response is limited to 3 MB of decoded content and uses a 30-second HTTP timeout. HTTP errors and unexpected article structure fail the command. Files are staged in a temporary directory; the completed manifest and files are published together by renaming that directory. A failed download leaves no partially published snapshot.

`copilot ingest --snapshot ...` performs the following steps:

1. Validate the manifest, exact source list, filename constraints, license hash, snapshot identity, and all page hashes.
2. Parse each saved HTML article using Beautiful Soup. Keep headings, prose, lists, tab labels, and fenced code blocks; exclude surrounding navigation, heading-link glyphs, line numbers, scripts, and styles.
3. Track the heading hierarchy and section anchors. Normalize the document to text with headings. Build chunks in document order.
4. Connect to PostgreSQL and take the import lock. Check whether an existing document has the same snapshot hash, extracted content hash, and pipeline version.
5. Insert missing documents. Replace each document's chunks with the same deterministic IDs and contents. Commit only when the whole collection succeeds.

For example, the **Path Parameters** page contains the **Path parameters with types** section. Its code includes `item_id: int`. That code remains indented inside a fenced block. Its chunk records the section path `Path Parameters > Path parameters with types`, anchor `path-parameters-with-types`, content hash, and document relationship. A join supplies the source URL, title, and snapshot ID. A future citation can combine the URL with the anchor; this phase does not generate answers or citations.

`GET /ready` opens a short-lived database connection and checks the current schema. A connection, query, or initialization failure yields HTTP 503 with `{"status":"not_ready"}`. Logs include the exception class, never the connection string or exception message. `/health` does no database work.

## 5. Important files

| File | Responsibility |
| --- | --- |
| `pyproject.toml`, `uv.lock`, `.python-version` | Package, CLI entry point, Python requirements, exact resolved dependency versions, default Python 3.12. |
| `.env.example`, `.gitignore` | Local configuration example and exclusion of secrets, environment, and caches. |
| `compose.yaml` | PostgreSQL 17 with pgvector 0.8.2, localhost port 5433, persistent volume, database health check. |
| `src/support_copilot/app.py` | The two HTTP endpoints; no ingestion endpoint or answer API. |
| `src/support_copilot/cli.py` | `fetch-docs`, `init-db`, and `ingest`; nonzero exits and sanitized failure messages. |
| `src/support_copilot/snapshot.py` | Fixed source selection, bounded downloads, manifest models, hash validation, snapshot publication. |
| `src/support_copilot/corpus.py` | HTML extraction, document normalization, chunk grouping, hashes, and IDs. |
| `src/support_copilot/db.py` | Environment loading, connections, initialization, readiness queries, transactional storage. |
| `src/support_copilot/schema.sql` | Tables, uniqueness and foreign-key constraints, extension, schema version. |
| `src/support_copilot/events.py` | JSON application events for download, ingestion, initialization, and failures. Uvicorn keeps its normal server logs. |
| `data/snapshots/fastapi-d4f83a093dd1b2ab/` | The six downloaded HTML files, manifest, and unmodified upstream license. |
| `tests/` | Extraction, saved-source preservation, manifest failure cases, HTTP behavior, and database integration tests. Synthetic fixtures are explicitly labelled as such. |

## 6. Functions, IDs, and schema

`fetch_snapshot()` uses `download()` to save validated responses and builds a `Manifest`. `fingerprint()` hashes the ordered page metadata and license hash. `load_snapshot()` verifies the saved collection without network access. Identical raw collections have the same snapshot ID even when downloaded later. Raw HTML layout changes can create a new snapshot even if the visible prose is unchanged.

`extract_html()` returns a title and ordered `Section` records. `document_content()` combines the normalized sections for storage. `make_chunks()` groups blocks within each section up to a **1,600-character soft target**, then prepends the full heading path. It never splits a block to enforce the target and never merges across section boundaries. There is no overlap or tokenization.

`stable_id()` hashes a JSON array rather than ambiguous string concatenation:

- Snapshot ID: `fastapi-` plus the first 16 hexadecimal characters of the full manifest fingerprint. The full 64-character fingerprint is retained and checked.
- Document ID: SHA-256 of `[snapshot_id, source_url]`.
- Chunk ID: SHA-256 of `[document_id, pipeline_version, ordinal, section_anchor, chunk_content_hash]`.

The extractor/chunker identifier is `html-sections-blocks-v1-1600`. Identical inputs and pipeline produce identical IDs. A new snapshot intentionally gets new document and chunk IDs. A changed block or ordering can change chunk IDs. This is stable identity within a pinned corpus, not cross-version semantic identity. A pipeline mismatch on an already stored document is rejected instead of silently changing its evidence. Future extractor changes will need an explicit corpus migration/versioning decision.

`initialize()` executes the packaged SQL transactionally; running it again is harmless for this schema. It is an initialization script, not a schema migration framework. `connect()` sets a three-second connection timeout and ten-second per-statement timeout. `ingest()` validates and extracts before any writes, then commits the complete collection using Psycopg's connection context manager.

| Table | Main fields and constraints |
| --- | --- |
| `schema_version` | Version 1; used by readiness. |
| `documents` | Primary-key ID; unique `(snapshot_id, source_url)`; title, capture time, full snapshot hash, raw hash, normalized content/hash, pipeline version. |
| `chunks` | Primary-key ID; foreign key to document; unique `(document_id, ordinal)`; section path, anchor, text, content hash. |

Source metadata is normalized: it lives once on the document and is available to every chunk through its foreign key. No vector column, full-text index, or unused future schema is present. `CREATE EXTENSION IF NOT EXISTS vector` verifies the requested database foundation is available.

## 7. Commands and expected behavior

Run commands from the project root. Docker must be running. Use the example password only for this local development service.

```bash
uv sync --locked
cp .env.example .env
docker compose up -d --wait
uv run copilot init-db
uv run copilot ingest --snapshot data/snapshots/fastapi-d4f83a093dd1b2ab
uv run copilot ingest --snapshot data/snapshots/fastapi-d4f83a093dd1b2ab
uv run uvicorn support_copilot.app:app --host 127.0.0.1 --port 8000
```

Skip the copy when `.env` already exists. `init-db` emits `schema_initialized`. Both ingestion commands report 6 documents and 81 chunks; those are processed totals, not counts of newly inserted rows. Application events go to stderr and the ingestion result goes to stdout as JSON.

In a separate terminal:

```bash
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/ready
docker compose exec -T db psql -U copilot -d copilot -c 'SELECT count(*) FROM documents; SELECT count(*) FROM chunks;'
```

Expect `200 {"status":"ok"}`, `200 {"status":"ready"}`, and counts 6 / 81. To observe an outage, run `docker compose stop db`, query both endpoints again, then restore the database with `docker compose up -d --wait`. Health stays 200 and readiness becomes 503 while the database is stopped.

To download a fresh collection:

```bash
uv run copilot fetch-docs
```

Use the printed directory in `ingest --snapshot`. A later download is not guaranteed to reproduce the included bytes. Preserve the included snapshot for comparisons. New snapshots coexist in the database; counts across all snapshots will then exceed 6 / 81.

Tests and formatting:

```bash
uv run pytest -m 'not integration' -q
TEST_DATABASE_URL=postgresql://copilot:local-development-only@127.0.0.1:5433/copilot uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
```

Database tests create unique schemas and drop only those schemas during cleanup. They do not delete the saved corpus. They need a role permitted to create schemas; initialize the normal project database first so pgvector already exists. Plain `uv run pytest` skips the three integration tests when `TEST_DATABASE_URL` is absent. No test downloads live documentation.

## 8. Actual verification results

Observed on **9 November 2026**, using Python 3.12.0 and the locked dependencies:

| Check | Observed result |
| --- | --- |
| Official downloads | Six HTML responses plus the upstream MIT license saved; no fabricated official content. |
| Docker Compose | `pgvector/pgvector:0.8.2-pg17` pulled and local service became healthy. |
| Initialization | Real database initialized; integration test also initialized twice successfully. |
| Complete test suite | **24 passed**: 21 offline tests and 3 PostgreSQL integration tests. |
| Static/style checks | Ruff check and format check passed. |
| Running Uvicorn | Startup completed; live `/health` and `/ready` returned HTTP 200. |
| Missing schema | Integration test observed `/ready` 503 before initialization and 200 afterward. |
| Database outage | Live `/health` stayed 200; `/ready` returned 503 after stopping PostgreSQL. |
| Real corpus ingestion | **6 documents, 81 chunks**. |
| Repeat real ingestion | All rows, IDs, hashes, and metadata unchanged; counts stayed 6 / 81. |
| Snapshot corruption | Altered page bytes were rejected before modifying stored data. |
| Transaction rollback | An injected constraint failure on the sixth synthetic document left zero imported records. |
| Code preservation | All **83** original article code blocks retained verbatim inside fences; six representative code identifiers also checked. |

The complete row-state SHA-256 before and after real re-ingestion was `c28b6597b25b1eb6a2fa761ca7a5bdd2d65bfdd334217b2f976b03fe27ae29c6`. This is a local verification record, not an evaluation score or a portable benchmark artifact.

The test suite emits one upstream `StarletteDeprecationWarning`: the currently resolved TestClient deprecates HTTPX in favor of HTTPX2. Tests pass; the warning has not been suppressed. It does not affect the running endpoints. Follow the upstream test-client migration before updating those dependencies in a later maintenance change.

Initial sandboxed network access failed DNS resolution; downloads and dependency installation succeeded with the environment's approved network access. Docker was initially stopped and was started for verification. Neither remains a blocker.

Snapshot: `fastapi-d4f83a093dd1b2ab`, captured on 9 November 2026 at **17:22:59 IST** (the manifest stores UTC). Full fingerprint: `d4f83a093dd1b2ab86e0bda39fd378393e2c1de4935c6bc59ca5f4f03b603ab4`.

| Selected official source | Chunks | Preserved code blocks |
| --- | ---: | ---: |
| [Path Parameters](https://fastapi.tiangolo.com/tutorial/path-params/) | 20 | 16 |
| [Query Parameters](https://fastapi.tiangolo.com/tutorial/query-params/) | 7 | 20 |
| [Request Body](https://fastapi.tiangolo.com/tutorial/body/) | 11 | 9 |
| [Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/) | 16 | 11 |
| [Handling Errors](https://fastapi.tiangolo.com/tutorial/handling-errors/) | 16 | 17 |
| [Security — First Steps](https://fastapi.tiangolo.com/tutorial/security/first-steps/) | 11 | 10 |

These cover routing, parameter/body validation, dependencies, errors, and introductory bearer authentication. They do not cover complete JWT/password flows or all FastAPI features.

## 9. Design choices and tradeoffs

- **Rendered HTML snapshot:** The official pages already include rendered code examples, unlike source Markdown that can require resolving include directives. Keeping the raw HTML allows offline verification. It includes website layout bytes that are irrelevant to answers and can change independently of documentation.
- **Bounded selection:** Six pages are enough to exercise ingestion and later build focused support cases. A crawl would make provenance review and evaluation scope harder to control.
- **Heading/block chunking:** It is deterministic and inspectable, and avoids breaking Python indentation. A tokenizer or semantic chunker could fit model limits better but is premature before provider selection. The largest current chunk is 1,694 characters including its heading; the target is deliberately soft.
- **Direct Psycopg and SQL:** Three small tables do not need an ORM. SQL makes constraints and transactions visible. As the schema evolves, explicit migrations may become useful.
- **Atomic replacement of chunks:** Deleting and recreating a document's chunks in the transaction keeps exactly the expected chunk set and repairs missing chunks. It does more writes than an incremental diff and is suitable for this small corpus. Document rows remain unchanged on a valid repeat import.
- **Synchronous endpoints:** FastAPI runs the ordinary `def` readiness handler in its thread pool, so synchronous database I/O is straightforward. There is no connection pool or throughput claim.
- **Explicit initialization:** Compose creates the PostgreSQL database; `init-db` installs the extension and tables. A reachable server alone does not prove the schema exists. Initialization is not hidden in API startup or a one-time volume hook.
- **Reproducibility boundaries:** `uv.lock` pins Python packages. The Compose image uses a version tag, not an immutable image digest. The saved corpus, pipeline identifier, and hashes make data preparation reproducible; Python/platform combinations beyond the tested environment have not been validated.

Official implementation references consulted: [FastAPI server startup](https://fastapi.tiangolo.com/deployment/manually/), [Psycopg transaction contexts](https://www.psycopg.org/psycopg3/docs/basic/transactions.html), and [pgvector installation](https://github.com/pgvector/pgvector). The source license is retained in the snapshot.

## 10. Failure cases and known limitations

- A missing database URL, unreachable database, missing schema, or missing extension makes readiness return 503. CLI failures return exit code 1 and a sanitized error category. Error text deliberately omits credentials; inspect configuration and structured event types when diagnosing failures.
- A wrong source list, title, filename, checksum, or snapshot identity fails ingestion. Malformed HTML without the expected article/title or usable content fails extraction. Failed downloads do not substitute invented text.
- Checksums are integrity checks, not a trust boundary. This command is for the local saved corpus, not an untrusted upload service.
- The extractor targets this website layout. It is not a general HTML-to-Markdown converter: images and cross-page links are not retained as evidence, tables/lists are flattened, and unusual nested markup may lose formatting. All code blocks in this actual snapshot are covered by preservation tests.
- Alternate Python-version examples and repeated article notices remain in the corpus. This can create redundant evidence. We have not measured retrieval effects or removed text using speculative quality heuristics.
- Snapshot version means captured website bytes, not a FastAPI package release. Official page URLs can change after capture. Raw snapshots and attribution must remain available alongside future evaluation runs.
- Reinitialization does not migrate incompatible existing schemas. Database readiness checks representative columns and version, not every constraint or data invariant.
- PostgreSQL credentials are local development credentials, the database is bound to localhost, and there is no API authentication, multi-tenant security, backup workflow, or production deployment.
- Passing ingestion tests establishes data-pipeline behavior. It says nothing about retrieval recall, answer correctness, hallucination, latency under load, or model safety.

## 11. Five likely interview questions

**Why build ingestion before calling an LLM?**

The evaluation needs traceable, stable evidence. I first verified that the same source snapshot produces the same chunks and that failures cannot leave partial imports. Otherwise a later score change could be caused by inconsistent data preparation.

**How do you prevent duplicate data?**

Documents have deterministic IDs and a unique snapshot/URL constraint. Chunks have deterministic IDs and unique document/ordinal positions. Ingestion serializes writes and replaces each document's chunks inside one transaction. I verified both counts and the complete stored row state across repeat ingestion.

**Why not split every fixed number of characters?**

That could split code in the middle of a statement or detach it from a heading. I group whole blocks within sections and keep the heading path. The tradeoff is a soft size limit; I have not claimed it is optimal for any embedding model.

**How do you handle a documentation update?**

I download a new snapshot and retain its raw hashes, manifest, and capture time. Changed source bytes produce a new snapshot identity and new document/chunk IDs. Old and new snapshots coexist. Later evaluation runs must record the selected snapshot explicitly.

**What have you proven about the copilot so far?**

Only its foundation: real downloads, extraction with preserved examples, stable IDs, repeatable transactional storage, and operational endpoints. Twenty-four tests and live checks passed. There are no answers, retrieval results, model benchmarks, or production users to claim yet.

## 12. Hands-on exercise

1. Start the database, initialize it, and ingest the included snapshot using the commands above.
2. Run this query to inspect one code-bearing section and its provenance:

   ```bash
   docker compose exec -T db psql -U copilot -d copilot -c "SELECT c.id, d.source_url, d.snapshot_id, c.section, c.content FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.anchor = 'path-parameters-with-types';"
   ```

3. Save the printed chunk ID. Re-run ingestion and the query. Explain why the ID is unchanged.
4. Copy the snapshot directory to `/tmp/copilot-exercise` and append one space to its copied `page-0.html`. Try ingesting the copy. Expect exit code 1 and `command_failed` with a validation error. Confirm the original database counts still read 6 / 81. Preserve the original snapshot.
5. With the API running, stop only the project database and compare `/health` with `/ready`. Restore it using `docker compose up -d --wait`. Explain why one endpoint remains healthy while the other fails.

Stop here. Phase 2 starts only after the explicit instruction **“continue to Phase 2.”**
