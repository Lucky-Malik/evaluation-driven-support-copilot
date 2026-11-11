import json
from pathlib import Path

import pytest

from support_copilot.evaluation.adversarial import (
    adversarial_summary,
    controlled_passages,
    evaluate_adversarial_case,
    load_adversarial,
    run_adversarial,
)

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data/evaluation/fastapi-adversarial-v1"
SNAPSHOT = ROOT / "data/snapshots/fastapi-d4f83a093dd1b2ab"


@pytest.fixture
def adversarial_data():
    return load_adversarial(DATASET, SNAPSHOT)


def test_dataset_and_injected_copies_preserve_original_corpus(adversarial_data):
    cases, passages, _ = adversarial_data
    assert len(cases) == 12
    assert all(c.case.provenance.review_status == "agent_inspected" for c in cases)
    attack = next(c for c in cases if c.attack_kind == "document_injection")
    original = passages[attack.case.evidence[0].chunk_id].model_dump()
    modified = controlled_passages(attack, passages)
    assert attack.injected_text in modified[0].content
    assert modified[0].content_sha256 != original["content_sha256"]
    assert passages[original["chunk_id"]].model_dump() == original


@pytest.mark.parametrize("kind", ["question_injection", "document_injection"])
def test_injection_is_payload_data_and_safe_scripted_answer_passes(
    adversarial_data, baseline_settings, provider_client, kind
):
    cases, passages, _ = adversarial_data
    item = next(c for c in cases if c.attack_kind == kind)
    client, state = provider_client
    record = evaluate_adversarial_case(item, passages, baseline_settings, client)
    request = state["calls"][0][1]
    marker = item.forbidden_markers[0]
    assert marker in request["input"]
    assert marker not in request["instructions"]
    assert "tools" not in request
    assert record["observations"]["marker_attack_success"] is False
    assert record["application"]["status"] == "completed"


def test_valid_citation_cannot_block_a_semantically_bad_scripted_answer(
    adversarial_data, baseline_settings, provider_client
):
    cases, passages, _ = adversarial_data
    item = cases[0]
    client, state = provider_client
    state["answer_override"] = item.forbidden_markers[0]
    record = evaluate_adversarial_case(item, passages, baseline_settings, client)
    assert record["application"]["status"] == "completed"
    assert record["application"]["citations"]
    assert record["observations"]["marker_attack_success"] is True
    assert adversarial_summary([record])["metrics"]["marker_attack_success"] == {"value": 1, "n": 1}


def test_invented_citation_is_blocked_and_not_counted_as_safe_judgment(
    adversarial_data, baseline_settings, provider_client
):
    cases, passages, _ = adversarial_data
    client, state = provider_client
    state["citation_id"] = "invented-admin"
    record = evaluate_adversarial_case(cases[0], passages, baseline_settings, client)
    assert record["application"]["error"]["code"] == "invalid_citation"
    assert record["observations"]["marker_attack_success"] is None
    assert record["application"]["draft"] is not None


def test_benign_refusal_metric_and_errors_have_separate_denominators(
    adversarial_data, baseline_settings, provider_client
):
    cases, passages, _ = adversarial_data
    item = next(c for c in cases if c.case.id == "adv-control-security")
    client, state = provider_client
    good = evaluate_adversarial_case(item, passages, baseline_settings, client)
    state["status"] = "insufficient_evidence"
    refused = evaluate_adversarial_case(item, passages, baseline_settings, client)
    state["http_status"] = 429
    failed = evaluate_adversarial_case(item, passages, baseline_settings, client)
    summary = adversarial_summary([good, refused, failed])
    assert summary["metrics"]["inappropriate_refusal"] == {"value": 0.5, "n": 2}
    assert summary["application_errors"] == 1
    assert summary["application_usage"]["reported_total_tokens"] == 240


def test_controlled_artifact_cannot_be_mistaken_for_retrieval_run(
    tmp_path, baseline_settings, provider_client
):
    client, state = provider_client
    output = tmp_path / "adversarial"
    result = run_adversarial(DATASET, SNAPSHOT, output, baseline_settings, client)
    manifest = json.loads((output / "run.json").read_text())
    assert manifest["kind"] == "controlled_adversarial_generation"
    assert manifest["retrieval_exercised"] is False
    assert result["cases"] == 12
    assert len(state["calls"]) == 12
    with pytest.raises(ValueError, match="new adversarial"):
        run_adversarial(DATASET, SNAPSHOT, output, baseline_settings, client)
