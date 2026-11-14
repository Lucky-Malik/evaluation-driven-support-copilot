# Portfolio report — Evaluation-driven support copilot

## Problem and result

A support answer needs inspectable evidence, and a retrieval change needs repeatable evaluation before it can be called an improvement. This project connects those workflows: ask questions against pinned FastAPI documentation, inspect citations, and compare saved experiments using quality, score coverage, errors, latency, and token usage.

The five-phase implementation includes FastAPI, deterministic ingestion into PostgreSQL/pgvector, vector/keyword/RRF hybrid retrieval, structured cited answers, quality and adversarial evaluation suites, Streamlit, regression gates, CI, and container packaging. The UI consumes the existing API; evaluation browsing reads saved artifacts without model calls.

## Evidence available

| Evidence | Observation | Practical limit |
| --- | --- | --- |
| Pinned corpus | Six official FastAPI pages, 81 chunks | Incomplete snapshot, not a named release |
| Quality dataset | 20 development and 10 held-out cases | Agent-inspected; zero user-reviewed labels recorded |
| Adversarial dataset | 12 attack/control cases | Validation is not live effectiveness |
| Keyword development retrieval | Recall@5 0.6923, MRR@5 0.5962; 13 answerable cases | No answer generation; not a vector/hybrid comparison |
| Live vector/hybrid/answer quality | Unmeasured | Needs provider access and matched runs |
| Dollar cost | Unavailable | Token usage is recorded; verified pricing is not configured |

Retrieval values come from the [Phase 4 report](../phase-4/keyword-dev.json) and its [failure notes](../phase-4/results.md). They are historical measurements, not new Phase 5 quality claims. Vector remains the default because live evidence does not yet justify promoting hybrid.

## Design decisions

- Preserve corpus, prompts, settings, case identities, usage, and failures in artifacts so comparisons can be audited.
- Keep score coverage visible and reject regressions hidden by missing judgments.
- Separate dashboard browsing from evaluation execution so filters and rerenders never launch paid work.
- Test failures: ambiguous timeouts are not retried, failed submissions clear stale answers, and incompatible evaluations cannot be compared.
- Reuse one application image for API and UI processes; preserve database storage and mount saved runs read-only in the UI.

## Demonstration

1. Validate both datasets without credentials and inspect recorded keyword evidence.
2. Configure the key/corpus, start API and UI, and ask “How do I require item_id to be an integer path parameter?” Open the cited source and retrieved passage.
3. Try ambiguity and out-of-corpus questions. Show the observed outcome, including any failure, without promising a particular live response.
4. Generate a development evaluation; inspect categories, failures, judge coverage, and usage; compare a matched candidate.
5. Run `copilot eval check` and report its outcome alongside coverage and dataset limitations.

## Local delivery verification

Verified on 14 November 2026 with Python 3.12:

- **143 tests passed, 3 paid live tests skipped**, including real PostgreSQL integration, keyword regression, Streamlit AppTest flows, artifact integrity, and saved-run gate checks.
- Ruff lint and formatting, dataset/adversarial validation, and wheel/source-distribution builds passed.
- The Docker image built; bundled dataset validation ran as its non-root user. The snapshot permissions are normalized inside the image without changing the local source snapshot.
- API and Streamlit containers reached healthy states using the existing local database. No live provider requests were made.
- The existing Starlette TestClient deprecation warning remains. Direct browser inspection was unavailable because the browser access host was disconnected; AppTest covered UI interactions.

Hosted GitHub Actions execution and public deployment have not been performed. Scripted tests establish application behavior, not live answer quality or guardrail effectiveness.

## Next evidence to collect

Run paid baseline/hybrid/adversarial experiments on identical evidence, review labels and sampled judgments with a human, select settings on development data, and evaluate the frozen configuration on the held-out split. Broader corpus coverage, larger reviewed datasets, authentication, and cost controls are needed before a production claim.
