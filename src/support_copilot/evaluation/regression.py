"""A deterministic gate over saved, matched quality evaluations; no model calls."""

import math
from pathlib import Path

from support_copilot.evaluation.runner import compare_runs


def check_regression(
    baseline: Path, candidate: Path, max_drop: float = 0.02, max_latency_ratio: float | None = None
) -> dict:
    if not math.isfinite(max_drop) or not 0 <= max_drop <= 1:
        raise ValueError("max-drop must be a finite number between 0 and 1")
    if max_latency_ratio is not None and (
        not math.isfinite(max_latency_ratio) or max_latency_ratio <= 0
    ):
        raise ValueError("max-latency-ratio must be finite and positive")
    comparison = compare_runs(baseline, candidate)
    left = comparison["left_summary"]["overall"]
    right = comparison["right_summary"]["overall"]
    failures = []
    for metric, pair in comparison["paired_metrics"].items():
        baseline_n = left["metrics"][metric]["n"]
        if baseline_n == 0:
            failures.append(f"{metric}: baseline has no score coverage")
        elif pair["n_pairs"] < baseline_n:
            failures.append(f"{metric}: candidate lost baseline score coverage")
        elif pair["delta"] is None or not math.isfinite(pair["delta"]):
            failures.append(f"{metric}: comparison has no finite delta")
        elif pair["delta"] < -max_drop - 1e-12:
            failures.append(f"{metric}: score dropped more than {max_drop:g}")
    for field in ("application_errors", "judge_failures", "judge_not_run"):
        if right[field] > left[field]:
            failures.append(f"{field}: candidate increased from {left[field]} to {right[field]}")
    if max_latency_ratio is not None:
        before = left["application_latency"]["p95_ms"]
        after = right["application_latency"]["p95_ms"]
        if before is None or after is None or not math.isfinite(before) or before <= 0:
            failures.append("application_latency: no usable baseline/candidate p95")
        elif not math.isfinite(after) or after > before * max_latency_ratio:
            failures.append("application_latency: candidate p95 exceeded the allowed ratio")
    return {
        "passed": not failures,
        "failures": failures,
        "thresholds": {"max_drop": max_drop, "max_latency_ratio": max_latency_ratio},
        "comparison": comparison,
        "note": "A regression gate on these cases only; not a significance or safety test.",
    }
