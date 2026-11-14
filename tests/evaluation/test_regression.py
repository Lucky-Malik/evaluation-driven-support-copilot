import json

import pytest

from support_copilot.cli import main
from support_copilot.corpus import sha256
from support_copilot.evaluation.artifacts import read_run, write_json
from support_copilot.evaluation.regression import check_regression


def rewrite_records(folder, mutate):
    meta, records = read_run(folder)
    for record in records:
        mutate(record)
    raw = "".join(json.dumps(r) + "\n" for r in records).encode()
    (folder / "cases.jsonl").write_bytes(raw)
    meta["results_sha256"] = sha256(raw)
    write_json(folder / "run.json", meta)


def test_identical_scores_pass(make_run):
    left, _ = make_run("baseline")
    right, _ = make_run("candidate")
    assert check_regression(left, right)["passed"]


def test_score_drop_and_cli_exit(make_run, monkeypatch, capsys):
    left, _ = make_run("baseline")
    right, _ = make_run("candidate")
    rewrite_records(right, lambda r: r["scores"].update(recall_at_k=0.5))
    result = check_regression(left, right)
    assert not result["passed"]
    assert any("recall_at_k" in f for f in result["failures"])
    monkeypatch.setattr("sys.argv", ["copilot", "eval", "check", str(left), str(right)])
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 1
    assert json.loads(capsys.readouterr().out)["passed"] is False


def test_coverage_loss_cannot_pass_by_excluding_failed_judgments(make_run, judge_client):
    left, _ = make_run("baseline")
    judge_client[1]["malformed"] = True
    right, _ = make_run("candidate")
    result = check_regression(left, right)
    assert not result["passed"]
    assert any("lost baseline score coverage" in f for f in result["failures"])
    assert any("judge_failures" in f for f in result["failures"])
    assert not check_regression(right, right)["passed"]


def test_latency_gate_is_optional(make_run):
    left, _ = make_run("baseline")
    right, _ = make_run("candidate")
    rewrite_records(left, lambda r: r["application"].update(elapsed_ms=10))
    rewrite_records(right, lambda r: r["application"].update(elapsed_ms=100))
    assert check_regression(left, right)["passed"]
    assert not check_regression(left, right, max_latency_ratio=2)["passed"]


def test_invalid_baseline_latency_cannot_pass(make_run):
    left, _ = make_run("baseline")
    right, _ = make_run("candidate")
    rewrite_records(left, lambda r: r["application"].update(elapsed_ms=float("nan")))
    assert not check_regression(left, right, max_latency_ratio=2)["passed"]


@pytest.mark.parametrize("drop", [-1, 2, float("nan"), float("inf")])
def test_invalid_thresholds_fail_before_reading_files(tmp_path, drop):
    with pytest.raises(ValueError, match="max-drop"):
        check_regression(tmp_path, tmp_path, max_drop=drop)


def test_cannot_compare_different_k(make_run, baseline_settings):
    left, _ = make_run("baseline")
    right, _ = make_run("candidate", settings=baseline_settings.model_copy(update={"top_k": 3}))
    with pytest.raises(ValueError, match="different k"):
        check_regression(left, right)
