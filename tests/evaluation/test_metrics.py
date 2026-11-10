import pytest

from support_copilot.evaluation.metrics import (
    aggregate,
    deterministic_scores,
    latency_summary,
    retrieval_scores,
)


def test_hand_calculated_recall_and_reciprocal_rank():
    result = retrieval_scores(["irrelevant", "b", "other", "a"], {"a", "b", "c"}, 3)
    assert result["recall_at_k"] == pytest.approx(1 / 3)
    assert result["mrr_at_k"] == pytest.approx(1 / 2)
    assert retrieval_scores(["x", "y"], {"a"}, 2) == {"recall_at_k": 0, "mrr_at_k": 0}


def test_duplicates_use_rank_slots_but_do_not_inflate_recall():
    result = retrieval_scores(["a", "a", "b"], {"a", "b"}, 2)
    assert result == {"recall_at_k": 0.5, "mrr_at_k": 1}


def test_no_positive_evidence_is_not_perfect_retrieval():
    assert retrieval_scores(["x"], set(), 5) == {"recall_at_k": None, "mrr_at_k": None}
    with pytest.raises(ValueError):
        retrieval_scores([], {"a"}, 0)


def test_citation_url_and_id_validity(dataset_bundle, make_answer):
    _, cases, _, _ = dataset_bundle
    case = cases[0]
    answer = make_answer(case)
    answer.citations[0].source_url = "https://example.com/invented"
    result = deterministic_scores(case, answer, answer.retrieved_passages, True, 5)
    assert result["citation_validity"] == 0.5
    answer.citations = []
    assert (
        deterministic_scores(case, answer, answer.retrieved_passages, True, 5)["citation_validity"]
        == 0
    )


def test_application_error_does_not_invent_retrieval_results(dataset_bundle):
    case = dataset_bundle[1][0]
    result = deterministic_scores(case, None, [], False, 5)
    assert result["outcome_accuracy"] == 0
    assert result["recall_at_k"] is None
    assert result["citation_validity"] is None


def test_percentiles_have_explicit_small_sample_behavior():
    result = latency_summary([1, 2, 3, 4])
    assert result == {"n": 4, "mean_ms": 2.5, "p50_ms": 2.5, "p95_ms": 4}
    assert latency_summary([])["p95_ms"] is None


def test_null_judgments_excluded_not_scored_as_zero():
    def record(value, status):
        return {
            "scores": {"answer_correctness": value},
            "application": {
                "status": "completed",
                "elapsed_ms": 10,
                "trace": {"provider_calls": []},
            },
            "judge": {"status": status, "elapsed_ms": 5, "provider_call": None},
        }

    result = aggregate([record(0.5, "completed"), record(None, "failed")])
    assert result["metrics"]["answer_correctness"] == {"value": 0.5, "n": 1}
    assert result["judge_failures"] == 1
    assert result["judge_usage"]["estimated_cost_usd"] is None
