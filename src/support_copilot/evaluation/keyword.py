from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from support_copilot.evaluation.artifacts import environment_identity, write_json
from support_copilot.evaluation.dataset import load_dataset
from support_copilot.evaluation.metrics import (
    METRICS_VERSION,
    average,
    latency_summary,
    retrieval_scores,
)
from support_copilot.evaluation.runner import verify_database
from support_copilot.retrieval import keyword_retrieve
from support_copilot.settings import Settings, config_hash


def keyword_evaluation(
    dataset: Path, snapshot: Path, output: Path, url: str, settings: Settings
) -> dict:
    if settings.retrieval_mode != "keyword":
        raise ValueError("The free keyword evaluation requires COPILOT_RETRIEVAL_MODE=keyword")
    if output.exists():
        raise ValueError("Choose a new report filename")
    manifest, cases, passages, digest = load_dataset(dataset, snapshot)
    if settings.snapshot_id != manifest.snapshot_id:
        raise ValueError("Dataset and configured snapshot differ")
    verify_database(url, settings, passages, manifest.snapshot_hash)
    results = []
    for case in cases:
        if case.split != "dev":
            continue
        started = perf_counter()
        retrieved = keyword_retrieve(url, case.question, settings)
        elapsed = (perf_counter() - started) * 1000
        results.append(
            {
                "case": case.model_dump(mode="json"),
                "retrieved_passages": [p.model_dump() for p in retrieved],
                "elapsed_ms": round(elapsed, 3),
                "scores": retrieval_scores(
                    [p.chunk_id for p in retrieved],
                    {e.chunk_id for e in case.evidence},
                    settings.top_k,
                ),
            }
        )

    def summarize(rows: list[dict]) -> dict:
        return {
            "cases": len(rows),
            "metrics": {
                name: average([r["scores"][name] for r in rows if r["scores"][name] is not None])
                for name in ("recall_at_k", "mrr_at_k")
            },
            "latency": latency_summary([r["elapsed_ms"] for r in rows]),
        }

    report = {
        "kind": "keyword_retrieval_only",
        "recorded_at": datetime.now(UTC).isoformat(),
        "dataset_sha256": digest,
        "dataset_id": manifest.dataset_id,
        "snapshot_hash": manifest.snapshot_hash,
        "split": "dev",
        "model_calls": 0,
        "metrics_version": METRICS_VERSION,
        "settings": settings.model_dump(),
        "config_sha256": config_hash(settings),
        "environment": environment_identity(),
        "overall": summarize(results),
        "by_category": {
            category: summarize([r for r in results if r["case"]["category"] == category])
            for category in sorted({r["case"]["category"] for r in results})
        },
        "cases": results,
        "note": "Measures real PostgreSQL keyword retrieval only; no answer or safety scores.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, report)
    return {"report": str(output), "overall": report["overall"], "model_calls": 0}
