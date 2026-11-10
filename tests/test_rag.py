import psycopg
import pytest
from fastapi.testclient import TestClient

from support_copilot.app import app
from support_copilot.contracts import Answer
from support_copilot.errors import CopilotError
from support_copilot.rag import answer_question
from support_copilot.settings import config_hash


@pytest.fixture
def ask_client(monkeypatch, baseline_settings, provider_client, passage):
    sdk, state = provider_client
    monkeypatch.setattr("support_copilot.app.OpenAI", lambda **_: sdk)
    monkeypatch.setattr("support_copilot.app.api_key", lambda: "test-only")
    monkeypatch.setattr("support_copilot.app.database_url", lambda: "not-a-real-database")
    monkeypatch.setattr("support_copilot.app.load_settings", lambda: baseline_settings)
    monkeypatch.setattr(
        "support_copilot.rag.corpus_status", lambda *_: {"ready": True, "snapshot_hash": "b" * 64}
    )
    monkeypatch.setattr("support_copilot.rag.retrieve", lambda *_: [passage])
    with TestClient(app) as http:
        yield http, state


def test_answer_citations_and_trace(ask_client, passage, baseline_settings):
    http, state = ask_client
    response = http.post("/ask", json={"question": "How do I validate an integer path parameter?"})
    assert response.status_code == 200
    answer = Answer.model_validate(response.json())
    assert answer.citations[0].chunk_id == passage.chunk_id
    assert answer.citations[0].source_url == passage.source_url
    assert {c.chunk_id for c in answer.citations} <= {p.chunk_id for p in answer.retrieved_passages}
    assert answer.trace.request_id == response.headers["x-request-id"]
    assert answer.trace.config_sha256 == config_hash(baseline_settings)
    assert answer.trace.provider_calls[0].usage.input_tokens == 12
    assert answer.trace.provider_calls[1].usage.output_tokens == 20
    assert answer.trace.cost.status == "unavailable"
    assert answer.trace.cost.estimated_usd is None
    assert all(value >= 0 for value in answer.trace.timings_ms.values())
    assert len(state["calls"]) == 2


@pytest.mark.parametrize(
    "status, question",
    [
        ("insufficient_evidence", "What is the weather in Delhi?"),
        ("needs_clarification", "How do I validate it?"),
    ],
)
def test_nonanswer_contract(ask_client, status, question):
    http, state = ask_client
    state["status"] = status
    response = http.post("/ask", json={"question": question})
    assert response.status_code == 200
    answer = Answer.model_validate(response.json())
    assert answer.status == status
    assert answer.answer is None
    assert answer.citations == []
    assert bool(answer.clarification_question) == (status == "needs_clarification")


@pytest.mark.parametrize(
    "status, expected_code, expected_http",
    [
        (401, "provider_authentication", 503),
        (429, "provider_rate_limit", 503),
        (500, "provider_error", 502),
    ],
)
def test_provider_failure_is_sanitized(ask_client, status, expected_code, expected_http):
    http, state = ask_client
    state["http_status"] = status
    response = http.post("/ask", json={"question": "A normal question"})
    assert response.status_code == expected_http
    assert response.json()["error"]["code"] == expected_code
    assert "sk-secret-body" not in response.text
    assert response.json()["trace"]["provider_calls"][0]["usage"]["input_tokens"] == 12
    assert len(state["calls"]) == 2


def test_unknown_citation_rejected(ask_client):
    http, state = ask_client
    state["citation_id"] = "invented-id"
    response = http.post("/ask", json={"question": "A normal question"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_citation"
    assert len(response.json()["trace"]["provider_calls"]) == 2


def test_failed_citation_keeps_draft_and_retrieval_for_evaluation(
    ask_client,
    provider_client,
    baseline_settings,
    passage,
):
    _, state = ask_client
    sdk, _ = provider_client
    state["citation_id"] = "invented-id"
    with pytest.raises(CopilotError) as caught:
        answer_question("A question", baseline_settings, "test-url", sdk, "test-request")
    assert caught.value.retrieved_passages[0]["chunk_id"] == passage.chunk_id
    assert caught.value.retrieval_completed is True
    assert caught.value.candidate_draft["citation_ids"] == ["invented-id"]
    assert caught.value.trace["timings_ms"]["retrieval"] >= 0


def test_failed_retrieval_keeps_timing_without_claiming_completion(
    ask_client, provider_client, baseline_settings, monkeypatch
):
    def fail(*_):
        raise psycopg.OperationalError("Synthetic connection failure")

    monkeypatch.setattr("support_copilot.rag.retrieve", fail)
    sdk, _ = provider_client
    with pytest.raises(CopilotError) as caught:
        answer_question("A question", baseline_settings, "test-url", sdk, "test-request")
    assert caught.value.code == "database_unavailable"
    assert caught.value.retrieval_completed is False
    assert caught.value.retrieved_passages == []
    assert caught.value.trace["timings_ms"]["retrieval"] >= 0


def test_invalid_outcome_rejected(ask_client):
    http, state = ask_client
    state["invalid_draft"] = True
    response = http.post("/ask", json={"question": "A normal question"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_provider_output"


def test_timeout_keeps_partial_usage_and_does_not_retry(ask_client):
    http, state = ask_client
    state["timeout"] = True
    response = http.post("/ask", json={"question": "A normal question"})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "provider_timeout"
    assert "Sensitive" not in response.text
    assert response.json()["trace"]["provider_calls"][0]["usage"]["total_tokens"] == 12
    assert len(state["calls"]) == 2


def test_incomplete_corpus_makes_no_provider_calls(ask_client, monkeypatch):
    http, state = ask_client
    monkeypatch.setattr(
        "support_copilot.rag.corpus_status", lambda *_: {"ready": False, "snapshot_hash": None}
    )
    response = http.post("/ask", json={"question": "A normal question"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "corpus_not_ready"
    assert state["calls"] == []


def test_empty_retrieval_skips_generation(ask_client, monkeypatch):
    http, state = ask_client
    monkeypatch.setattr("support_copilot.rag.retrieve", lambda *_: [])
    response = http.post("/ask", json={"question": "A normal question"})
    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert len(state["calls"]) == 1


def test_empty_question_is_rejected(ask_client):
    http, state = ask_client
    assert http.post("/ask", json={"question": "  "}).status_code == 422
    assert state["calls"] == []


def test_missing_key_is_explicit_without_connecting(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(app) as http:
        response = http.post("/ask", json={"question": "A normal question"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "missing_api_key"
