import math
from collections import Counter
from statistics import mean, median

from support_copilot.contracts import Answer, Passage
from support_copilot.evaluation.dataset import Case

METRICS_VERSION = "chunk-metrics-v1"


def retrieval_scores(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> dict:
    if k < 1:
        raise ValueError("k must be positive")
    if not relevant_ids:
        return {"recall_at_k": None, "mrr_at_k": None}
    ranked = retrieved_ids[:k]
    recall = len(set(ranked) & relevant_ids) / len(relevant_ids)
    reciprocal_rank = next(
        (1 / rank for rank, item in enumerate(ranked, 1) if item in relevant_ids), 0.0
    )
    return {"recall_at_k": recall, "mrr_at_k": reciprocal_rank}


def deterministic_scores(
    case: Case, answer: Answer | None, passages: list[Passage], retrieval_completed: bool, k: int
) -> dict:
    scores = {
        "recall_at_k": None,
        "mrr_at_k": None,
        "citation_validity": None,
        "outcome_accuracy": float(answer is not None and answer.status == case.expected_status),
    }
    if retrieval_completed:
        scores.update(
            retrieval_scores([p.chunk_id for p in passages], {e.chunk_id for e in case.evidence}, k)
        )
    if answer is not None and answer.status == "answered":
        by_id = {passage.chunk_id: passage for passage in passages}
        valid = sum(
            c.chunk_id in by_id and c.source_url == by_id[c.chunk_id].source_url
            for c in answer.citations
        )
        scores["citation_validity"] = valid / len(answer.citations) if answer.citations else 0.0
    return scores


def average(values: list[float]) -> dict:
    return {"value": mean(values) if values else None, "n": len(values)}


def latency_summary(values: list[float]) -> dict:
    ordered = sorted(values)
    return {
        "n": len(values),
        "mean_ms": mean(values) if values else None,
        "p50_ms": median(values) if values else None,
        "p95_ms": ordered[math.ceil(0.95 * len(values)) - 1] if values else None,
    }


def usage_summary(records: list[dict], role: str) -> dict:
    calls = []
    incomplete_cases = 0
    for record in records:
        if role == "application":
            trace = record["application"].get("trace") or {}
            calls.extend(trace.get("provider_calls", []))
            incomplete_cases += record["application"]["status"] == "error"
        else:
            call = record["judge"].get("provider_call")
            if call:
                calls.append(call)
            incomplete_cases += record["judge"]["status"] == "failed" and not call
    usage = [call["usage"] for call in calls if call.get("usage") is not None]
    return {
        "reported_input_tokens": sum(u["input_tokens"] for u in usage),
        "reported_output_tokens": sum(u["output_tokens"] for u in usage),
        "reported_total_tokens": sum(u["total_tokens"] for u in usage),
        "calls_with_usage": len(usage),
        "calls_missing_usage": len(calls) - len(usage),
        "failed_cases_with_potentially_missing_usage": incomplete_cases,
        "estimated_cost_usd": None,
        "cost_status": "unavailable_no_verified_pricing",
    }


def aggregate(records: list[dict]) -> dict:
    names = (
        "recall_at_k",
        "mrr_at_k",
        "citation_validity",
        "outcome_accuracy",
        "answer_correctness",
        "faithfulness",
        "citation_support",
        "response_appropriateness",
    )
    scores = {}
    for name in names:
        values = [
            record["scores"][name] for record in records if record["scores"].get(name) is not None
        ]
        scores[name] = average(values)
    application_ms = [r["application"]["elapsed_ms"] for r in records]
    judge_ms = [r["judge"]["elapsed_ms"] for r in records if r["judge"]["status"] != "not_run"]
    return {
        "cases": len(records),
        "metrics": scores,
        "application_errors": sum(r["application"]["status"] == "error" for r in records),
        "judge_failures": sum(r["judge"]["status"] == "failed" for r in records),
        "judge_not_run": sum(r["judge"]["status"] == "not_run" for r in records),
        "application_latency": latency_summary(application_ms),
        "judge_latency": latency_summary(judge_ms),
        "application_usage": usage_summary(records, "application"),
        "judge_usage": usage_summary(records, "judge"),
    }


def summarize(records: list[dict]) -> dict:
    return {
        "overall": aggregate(records),
        "failure_counts": dict(
            Counter(tag for record in records for tag in record["failure_tags"])
        ),
        "by_category": {
            category: aggregate([r for r in records if r["case"]["category"] == category])
            for category in sorted({r["case"]["category"] for r in records})
        },
    }
