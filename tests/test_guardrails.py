import asyncio

import pytest
from fastapi.testclient import TestClient

from support_copilot.app import app
from support_copilot.errors import CopilotError
from support_copilot.guardrails import BodyLimitMiddleware, bounded_payload
from support_copilot.provider import generate
from support_copilot.rag import answer_question
from support_copilot.settings import load_prompt


@pytest.mark.parametrize("question", ["x" * 4001, " "])
def test_question_rejected_before_database_or_provider(
    question, baseline_settings, provider_client
):
    client, state = provider_client
    with pytest.raises(CopilotError, match="4000"):
        answer_question(question, baseline_settings, "unreachable-db", client, "test")
    assert state["calls"] == []
    with TestClient(app) as http:
        assert http.post("/ask", json={"question": question}).status_code == 422


def test_large_json_body_rejected_before_parsing_or_provider():
    with TestClient(app) as http:
        response = http.post("/ask", content=b"{" + b"x" * 17000)
    assert response.status_code == 413


def test_body_limit_counts_streamed_bytes_without_content_length():
    messages = iter(
        [
            {"type": "http.request", "body": b"a" * 9000, "more_body": True},
            {"type": "http.request", "body": b"b" * 9000, "more_body": False},
        ]
    )
    sent = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    async def inner(*_):
        pytest.fail("Oversized body reached the application")

    asyncio.run(BodyLimitMiddleware(inner)({"type": "http", "method": "POST"}, receive, send))
    assert sent[0]["status"] == 413


def test_utf8_context_budget_rejects_before_model_call(passage, baseline_settings, provider_client):
    client, state = provider_client
    large = passage.model_copy(update={"content": "界" * 22000})
    with pytest.raises(CopilotError, match="size limit"):
        generate(client, "Question", [large], baseline_settings, load_prompt(baseline_settings))
    assert state["calls"] == []
    with pytest.raises(CopilotError):
        bounded_payload({"value": "界" * 4}, limit=20)
