# Phase 4 measurements and failure notes

Recorded on 11 November 2026. The saved [keyword development report](keyword-dev.json) contains the exact labels, retrieved text, rankings, timings, settings, corpus/dataset hashes, and package/source identities.

## Real PostgreSQL retrieval measurement

The run used the original development split, the original 81-chunk corpus, keyword mode, English lexemes combined with OR, weighted section/body vectors, `ts_rank_cd`, top K=5, and no section filter. It made **zero model calls**.

| Cases | Eligible retrieval cases | Recall@5 | MRR@5 |
| --- | ---: | ---: | ---: |
| All 20 development cases | 13 | 0.6923 | 0.5962 |
| Ordinary questions | 8 | 0.6250 | 0.6250 |
| Exact identifiers | 5 | 0.8000 | 0.5500 |
| Ambiguity / missing evidence | 0 | Not applicable | Not applicable |

Nine answerable cases retrieved all their labelled evidence in the top five; four retrieved none. Retrieval latency over all twenty cases was mean **8.097 ms**, median **7.568 ms**, and nearest-rank p95 **11.515 ms**. This is a single local run, including database connection overhead, not a load test or production latency estimate. Answer latency, answer quality, live attack success, and user-review agreement were not measured. There is no provider cost for this keyword-only command; dollar estimates for hosted-model runs remain unavailable.

## Inspected misses

| Case | Observation | Interpretation |
| --- | --- | --- |
| `ordinary-01` | Integer path validation labels absent; the top result is required query parameters. | Shared request/parameter words can outrank the desired path-validation explanation. |
| `ordinary-06` | Automatic request-body processing label absent; mixed body/path/query sections rank first. | Related vocabulary does not guarantee retrieval of the precise explanatory section. |
| `ordinary-07` | The dependency-purpose label is absent; dependency declaration and alias sections are present. | Some alternative passages may still be useful; strict labelled-chunk recall alone cannot settle answer quality. |
| `identifier-05` | The `HTTPException.detail` label is absent; dependency/security passages fill the results. | A dotted identifier in a natural-language question is not guaranteed to behave like exact substring matching under the text-search parser. |

These are retrieval observations, not generated-answer failures. No labels were changed to improve the reported score. The test split was not queried for this measurement. The current rule was not selected by comparing a family of tuned configurations; it is the first explicit keyword baseline.

## Guardrail checks with scripted responses

The tests use the real SDK with an HTTP mock. The following are observed test behaviors, **not live model measurements**:

| Scenario | Observed behavior |
| --- | --- |
| Oversized question, streamed HTTP body, or generation payload | Rejected before a provider call. |
| Oversized judge payload | Separate judge failure, with no provider call and no invented score. |
| Injection inside question or copied document; scripted compliant answer | Attack remains in JSON data, never in instructions; marker-success flag is false. |
| Scripted invented citation | Production citation validator rejects it; the artifact retains the failed draft. |
| Scripted attack marker with a valid citation | The application accepts the structurally valid answer; the adversarial measurement flags marker success. This demonstrates a semantic gap in deterministic validation. |
| One scripted valid answer, one unnecessary refusal, one provider error on an answerable benign control | Refusal metric is 1/2, with one error reported separately. This verifies the denominator, not an actual 50% live refusal rate. |

Both successful enforcement and a deliberately exposed failure are retained in tests. Prompt instructions and citation membership cannot guarantee semantic safety. Inspecting marker-free answers and comparing them with criteria is still necessary.

## Baseline versus hybrid decision

**Pending credentials.** `OPENAI_API_KEY` is not configured and the actual database has zero hosted embeddings. A live adversarial command was attempted and stopped with the missing-key error. Vector/hybrid quality, latency, and cost comparisons therefore cannot be reported honestly.

Keep **vector** as the application default. Hybrid is an explicit experiment; it is not claimed to improve quality. No reranker was added because there is no measured vector-versus-hybrid evidence to justify its complexity. The [phase guide](README.md) gives the exact live comparison and held-out workflow. Select settings on development results, then run the held-out split once choices are frozen; report errors and score coverage along with mean scores.
