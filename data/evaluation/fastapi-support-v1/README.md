# FastAPI support evaluation dataset v1

This starter dataset is pinned to the six-page snapshot `fastapi-d4f83a093dd1b2ab` and the `html-sections-blocks-v1-1600` chunking pipeline. All 30 cases were authored and inspected by the coding agent against the saved text on 10 November 2026. **None has been reviewed by the user.** Inspection is a provenance claim, not proof that every label is correct.

| Category | Development | Held-out test | Total |
| --- | ---: | ---: | ---: |
| Ordinary questions | 8 | 4 | 12 |
| Exact identifiers | 5 | 3 | 8 |
| Ambiguity | 3 | 1 | 4 |
| Missing evidence | 4 | 2 | 6 |
| Total | 20 | 10 | 30 |

`manifest.json` pins the corpus hash, chunking version, relevance unit, and SHA-256 of both JSONL files. Each line is one case: ID, split, category, question-family `group_id`, question, expected outcome, evidence chunk IDs with exact quotes, answer criteria, prohibited claims, and label provenance. Twenty answerable cases contain 21 evidence references. Clarification and insufficient-evidence cases have no positive retrieval labels; their retrieval metrics are not applicable.

Evidence was selected by reading reconstructed chunks from the saved HTML, including surrounding explanations and code. Positive quotes are checked verbatim by the validator. The ambiguity cases omit information necessary to choose a response; missing-evidence cases ask about matters outside this bounded snapshot. Neither quote matching nor agent inspection establishes exhaustive relevance. Another unlabelled chunk may also support a correct answer.

Run from the repository root:

```bash
uv run copilot eval validate
```

This validates labels and source identities without a database, API key, or paid calls. It checks duplicate IDs/questions, cross-split question families, evidence membership, exact quotes, and checksums. It does not measure model quality or detect every semantic duplicate.

## Label provenance and expansion

`machine_generated` means a draft has not been inspected; `agent_inspected` means the coding agent read the evidence and criteria; `user_reviewed` means the user actually reviewed that case. Reviewed states require an identified reviewer and date. Do not mark an entire file user-reviewed after reviewing only a sample. Reviewing a judge decision is a separate activity and does not promote dataset labels.

Expand toward approximately 100 cases in a new `fastapi-support-v2` directory, preserving v1 for existing runs:

1. Draft candidate questions from distinct documentation tasks, including exact API names, ambiguous requests, and plausible requests the corpus cannot answer. Mark new drafts `machine_generated`.
2. Reconstruct and read the referenced chunks. Check code as well as prose; write concrete required facts and prohibited claims. For missing evidence, inspect the corpus coverage before labelling absence. For ambiguity, specify what information a useful clarification should request.
3. Find other chunks that support the same answer and label them where appropriate. Avoid counting adjacent duplicate passages as independent facts. Remove ambiguous correctness criteria and semantic duplicates.
4. Assign related paraphrases to one `group_id` and keep the whole family in one split. Aim for roughly 60 development and 40 test cases with all four categories represented. Recheck overlap manually; the validator catches declared-family overlap, not semantic leakage.
5. Have the user inspect the question, expected outcome, evidence, criteria, and provenance for each case they approve. Record only the cases actually reviewed, with reviewer/date/notes. Rejected cases need correction and another review.
6. Update the new manifest's dataset ID and file hashes, then validate. Compute file hashes with `hashlib.sha256(path.read_bytes()).hexdigest()`; do not alter hashes to conceal unexpected changes. Freeze this version before reporting results.

Use development results to choose settings. Run the held-out split after choosing the configuration; do not repeatedly tune against it. These ten held-out cases are visible to the project's author and were authored by the same agent, so they are a small reserved test split, not an independently collected blind benchmark. Add independently reviewed tasks before making broad quality claims.

The [Phase 3 guide](../../../docs/phase-3/README.md) explains metric formulas, live runs, artifacts, judge review, and limitations.
