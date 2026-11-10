import json

import pytest

from support_copilot.evaluation.review import prepare_review, record_review


def test_sample_is_repeatable_spans_categories_and_does_not_claim_review(make_run, tmp_path):
    run, _ = make_run("full", limit=20)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    report = prepare_review(run, first, 5, 42)
    prepare_review(run, second, 5, 42)
    assert first.read_bytes() == second.read_bytes()
    packet = json.loads(first.read_text())
    assert len({item["result"]["case"]["category"] for item in packet["items"]}) == 4
    assert report["reviewed"] == 0
    assert packet["reviewer"] == ""
    assert all(item["decision"] == "pending" for item in packet["items"])
    assert not (run / "reviews").exists()


def test_review_records_agreement_separately_without_mutating_labels(make_run, tmp_path):
    run, _ = make_run("full", limit=3)
    original = (run / "cases.jsonl").read_bytes()
    path = tmp_path / "packet.json"
    prepare_review(run, path, 3, 42)
    packet = json.loads(path.read_text())
    packet["reviewer"] = "Synthetic test reviewer"
    for item, decision in zip(
        packet["items"], ["agree", "disagree", "unable_to_assess"], strict=True
    ):
        item["decision"] = decision
        item["notes"] = "Synthetic test note"
    path.write_text(json.dumps(packet))
    report = record_review(run, path)
    assert report["agreement_rate"] == 0.5
    assert report["agreement_denominator"] == 2
    assert report["counts"]["unable_to_assess"] == 1
    assert (run / "cases.jsonl").read_bytes() == original
    assert len(list((run / "reviews").glob("*.json"))) == 1


@pytest.mark.parametrize(
    "problem",
    [
        "no_reviewer",
        "changed_context",
        "no_disagreement_note",
        "pending",
        "missing_field",
        "wrong_type",
    ],
)
def test_invalid_reviews_are_not_recorded(make_run, tmp_path, problem):
    run, _ = make_run("run", limit=1)
    path = tmp_path / "packet.json"
    prepare_review(run, path, 1, 42)
    packet = json.loads(path.read_text())
    packet["reviewer"] = "Synthetic test reviewer"
    packet["items"][0]["decision"] = "agree"
    if problem == "no_reviewer":
        packet["reviewer"] = ""
    elif problem == "changed_context":
        packet["items"][0]["result"]["case"]["question"] = "Replaced question"
    elif problem == "no_disagreement_note":
        packet["items"][0]["decision"] = "disagree"
    elif problem == "missing_field":
        del packet["items"][0]["notes"]
    elif problem == "wrong_type":
        packet["reviewer"] = 17
    else:
        packet["items"][0]["decision"] = "pending"
    path.write_text(json.dumps(packet))
    with pytest.raises(ValueError):
        record_review(run, path)
    assert not (run / "reviews").exists()
