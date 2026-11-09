import pytest
from pydantic import ValidationError

from support_copilot.errors import CopilotError
from support_copilot.provider import embed, generate
from support_copilot.settings import load_prompt


def test_embedding_order_and_reported_usage(provider_client, baseline_settings):
    client, state = provider_client
    state["embedding_data"] = [
        {"index": 1, "embedding": [0, 1, 0]},
        {"index": 0, "embedding": [1, 0, 0]},
    ]
    result = embed(client, ["one", "two"], baseline_settings)
    assert result.vectors == [[1, 0, 0], [0, 1, 0]]
    assert result.call.usage.input_tokens == 12
    assert result.call.request_id == "req_embedding"
    assert state["calls"][0][1]["encoding_format"] == "float"
    assert state["calls"][0][1]["dimensions"] == 3


@pytest.mark.parametrize(
    "data",
    [
        [],
        [{"index": 0, "embedding": [0, 0, 0]}],
        [{"index": 0, "embedding": [1, 0]}],
        [{"index": 1, "embedding": [1, 0, 0]}],
    ],
)
def test_bad_embedding_output_is_rejected(provider_client, baseline_settings, data):
    client, state = provider_client
    state["embedding_data"] = data
    with pytest.raises(CopilotError, match="embedding"):
        embed(client, ["one"], baseline_settings)


@pytest.mark.parametrize("status", ["answered", "needs_clarification", "insufficient_evidence"])
def test_sdk_parses_each_outcome(provider_client, baseline_settings, passage, status):
    client, state = provider_client
    state["status"] = status
    result = generate(
        client, "A question", [passage], baseline_settings, load_prompt(baseline_settings)
    )
    assert result.draft.status == status
    assert result.failure is None
    assert result.call.usage.total_tokens == 120
    assert result.call.usage.cached_input_tokens == 10
    assert result.call.usage.reasoning_tokens == 5
    request = state["calls"][0][1]
    assert request["store"] is False
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True
    assert "tools" not in request


def test_semantically_inconsistent_schema_is_rejected(provider_client, baseline_settings, passage):
    client, state = provider_client
    state["invalid_draft"] = True
    with pytest.raises(ValidationError):
        generate(client, "Question", [passage], baseline_settings, load_prompt(baseline_settings))


@pytest.mark.parametrize(
    "field, value, failure",
    [
        ("refusal", True, "provider_refusal_or_empty_output"),
        ("response_status", "incomplete", "provider_incomplete"),
    ],
)
def test_refusal_and_truncation_keep_usage(
    provider_client, baseline_settings, passage, field, value, failure
):
    client, state = provider_client
    state[field] = value
    result = generate(
        client, "Question", [passage], baseline_settings, load_prompt(baseline_settings)
    )
    assert result.draft is None
    assert result.failure == failure
    assert result.call.usage.output_tokens == 20
