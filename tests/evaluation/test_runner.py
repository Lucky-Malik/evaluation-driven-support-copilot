import json

import pytest

from support_copilot.errors import CopilotError
from support_copilot.evaluation.artifacts import read_run
from support_copilot.evaluation.runner import compare_runs


def test_run_preserves_configuration_results_and_separate_usage(make_run):
    folder, result = make_run("baseline")
    manifest, records = read_run(folder)
    assert manifest["status"] == "completed"
    assert manifest["dataset_id"] == "fastapi-support-v1"
    assert manifest["split"] == "dev"
    assert len(manifest["case_ids"]) == len(records) == 3
    assert manifest["environment"]["source_sha256"]
    assert manifest["prompt_sha256"] and manifest["judge_prompt_sha256"]
    assert (folder / "answer_prompt.txt").exists()
    assert (folder / "selected_cases.json").exists()
    assert records[0]["gold_passages"] and records[0]["application"]["retrieved_passages"]
    assert result["overall"]["application_usage"]["reported_total_tokens"] == 3 * 132
    assert result["overall"]["judge_usage"]["reported_total_tokens"] == 3 * 240
    assert result["overall"]["application_usage"]["estimated_cost_usd"] is None
    assert result["overall"]["metrics"]["answer_correctness"]["n"] == 3


def test_failed_judge_keeps_answer_and_deterministic_scores(make_run, judge_client):
    _, state = judge_client
    state["malformed"] = True
    folder, result = make_run("failed-judge", limit=1)
    _, records = read_run(folder)
    assert records[0]["application"]["answer"] is not None
    assert records[0]["scores"]["recall_at_k"] == 1
    assert records[0]["scores"]["answer_correctness"] is None
    assert result["overall"]["judge_failures"] == 1
    assert result["overall"]["application_errors"] == 0
    assert result["overall"]["judge_usage"]["reported_total_tokens"] == 240


def test_failed_application_preserves_retrieval_but_skips_judge(
    make_run, monkeypatch, dataset_bundle, make_answer
):
    case = dataset_bundle[1][0]
    answer = make_answer(case)

    def fail(*_):
        error = CopilotError("provider_timeout", "Safe failure", 504)
        error.trace = answer.trace.model_dump()
        error.retrieved_passages = [p.model_dump() for p in answer.retrieved_passages]
        error.retrieval_completed = True
        raise error

    monkeypatch.setattr("support_copilot.evaluation.runner.answer_question", fail)
    folder, result = make_run("failed-app", limit=1)
    _, records = read_run(folder)
    assert records[0]["judge"]["status"] == "not_run"
    assert records[0]["scores"]["recall_at_k"] == 1
    assert records[0]["scores"]["outcome_accuracy"] == 0
    assert result["overall"]["application_errors"] == 1
    assert result["overall"]["judge_failures"] == 0


def test_failed_retrieval_timing_does_not_count_as_completed_retrieval(make_run, monkeypatch):
    def fail(*_):
        error = CopilotError("database_unavailable", "Safe database failure")
        error.trace = {"timings_ms": {"retrieval": 10.0}, "provider_calls": []}
        raise error

    monkeypatch.setattr("support_copilot.evaluation.runner.answer_question", fail)
    folder, _ = make_run("failed-retrieval", limit=1)
    _, records = read_run(folder)
    assert records[0]["scores"]["recall_at_k"] is None
    assert records[0]["scores"]["mrr_at_k"] is None
    assert records[0]["application"]["retrieval_completed"] is False


def test_unexpected_failure_leaves_interrupted_run_and_propagates(make_run, monkeypatch, tmp_path):
    def fail(*_):
        raise RuntimeError("Synthetic programming error")

    monkeypatch.setattr("support_copilot.evaluation.runner.answer_question", fail)
    with pytest.raises(RuntimeError, match="programming error"):
        make_run("interrupted")
    manifest = json.loads((tmp_path / "interrupted/run.json").read_text())
    assert manifest["status"] == "interrupted"
    assert manifest["completed_cases"] == 0
    with pytest.raises(ValueError, match="completed live"):
        read_run(tmp_path / "interrupted")


def test_refuses_to_overwrite_run(make_run):
    folder, _ = make_run("baseline")
    previous = (folder / "run.json").read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        make_run("baseline")
    assert (folder / "run.json").read_bytes() == previous


def test_compare_uses_matched_cases_and_reports_coverage(make_run, judge_client):
    left, _ = make_run("left")
    _, state = judge_client
    state["malformed"] = True
    right, _ = make_run("right")
    comparison = compare_runs(left, right)
    assert comparison["paired_metrics"]["recall_at_k"] == {
        "n_pairs": 3,
        "left_mean": 1,
        "right_mean": 1,
        "delta": 0,
    }
    assert comparison["paired_metrics"]["answer_correctness"]["n_pairs"] == 0
    assert comparison["paired_metrics"]["answer_correctness"]["delta"] is None
    assert comparison["right_summary"]["overall"]["judge_failures"] == 3


def test_comparison_rejects_different_case_subsets(make_run):
    left, _ = make_run("left", limit=1)
    right, _ = make_run("right", limit=2)
    with pytest.raises(ValueError, match="case_ids"):
        compare_runs(left, right)


def test_tampered_results_are_rejected(make_run):
    folder, _ = make_run("tamper")
    with (folder / "cases.jsonl").open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="checksum"):
        read_run(folder)
