import os
from uuid import uuid4

import pytest
from openai import OpenAI

from support_copilot.db import database_url
from support_copilot.rag import answer_question
from support_copilot.retrieval import corpus_status
from support_copilot.settings import api_key, load_settings

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_TESTS") != "1",
        reason="Paid smoke tests require explicit RUN_LIVE_TESTS=1",
    ),
]


@pytest.mark.parametrize(
    "question, expected_status",
    [
        ("How do I require the FastAPI path parameter item_id to be an integer?", "answered"),
        ("What is tomorrow's weather forecast for Delhi?", "insufficient_evidence"),
        ("How do I validate it?", "needs_clarification"),
    ],
)
def test_live_support_outcomes(question: str, expected_status: str) -> None:
    settings = load_settings()
    url = database_url()
    assert corpus_status(url, settings)["ready"], "Run copilot embed before the paid smoke tests"
    with OpenAI(api_key=api_key(), timeout=settings.timeout_seconds, max_retries=0) as client:
        answer = answer_question(question, settings, url, client, str(uuid4()))
    assert answer.status == expected_status
    retrieved = {passage.chunk_id for passage in answer.retrieved_passages}
    assert all(citation.chunk_id in retrieved for citation in answer.citations)
    if expected_status == "answered":
        assert answer.answer and answer.citations
        assert any(
            "/tutorial/path-params/" in item.source_url for item in answer.retrieved_passages
        )
    else:
        assert answer.answer is None and answer.citations == []
    assert len(answer.trace.provider_calls) == 2
    assert all(call.usage is not None for call in answer.trace.provider_calls)
