import json
from pathlib import Path

import httpx
import pytest
from openai import OpenAI

from support_copilot.contracts import Answer, Citation, ProviderCall, Trace, Usage
from support_copilot.evaluation.dataset import load_dataset
from support_copilot.evaluation.judge import load_judge_settings
from support_copilot.evaluation.runner import run_evaluation
from support_copilot.settings import config_hash

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data/evaluation/fastapi-support-v1"
SNAPSHOT = ROOT / "data/snapshots/fastapi-d4f83a093dd1b2ab"


@pytest.fixture(scope="session")
def dataset_bundle():
    return load_dataset(DATASET, SNAPSHOT)


@pytest.fixture
def judge_settings(monkeypatch):
    monkeypatch.setenv("COPILOT_JUDGE_MODEL", "test-only-judge")
    return load_judge_settings()


@pytest.fixture
def make_answer(dataset_bundle, baseline_settings):
    manifest, _, passages, _ = dataset_bundle

    def build(case, request_id="test-request"):
        gold = [passages[item.chunk_id] for item in case.evidence]
        retrieved = gold or [next(iter(passages.values()))]
        answered = case.expected_status == "answered"
        calls = [
            ProviderCall(
                operation="embedding",
                requested_model="test-embedding",
                returned_model="test-embedding",
                request_id="test-embed",
                usage=Usage(input_tokens=12, output_tokens=0, total_tokens=12),
            ),
            ProviderCall(
                operation="generation",
                requested_model="test-answer",
                returned_model="test-answer",
                request_id="test-answer",
                usage=Usage(input_tokens=100, output_tokens=20, total_tokens=120),
            ),
        ]
        trace = Trace(
            request_id=request_id,
            pipeline_version=baseline_settings.pipeline_version,
            config_sha256=config_hash(baseline_settings),
            prompt_version="answer-v1.txt",
            prompt_sha256="a" * 64,
            snapshot_id=manifest.snapshot_id,
            snapshot_hash=manifest.snapshot_hash,
            embedding_model=baseline_settings.embedding_model,
            embedding_dimensions=3,
            generation_model=baseline_settings.generation_model,
            top_k=baseline_settings.top_k,
            reasoning_effort="low",
            max_output_tokens=4096,
            timings_ms={"retrieval": 1.0, "total": 10.0},
            provider_calls=calls,
        )
        return Answer(
            status=case.expected_status,
            answer="Synthetic answer for a harness test." if answered else None,
            clarification_question="Which parameter?"
            if case.expected_status == "needs_clarification"
            else None,
            reason="Synthetic test fixture, not a model judgment.",
            citations=[
                Citation(
                    chunk_id=p.chunk_id, source_url=p.source_url, title=p.title, section=p.section
                )
                for p in gold
            ]
            if answered
            else [],
            retrieved_passages=retrieved,
            trace=trace,
        )

    return build


@pytest.fixture
def judge_client():
    state = {
        "requests": [],
        "http_status": 200,
        "override": None,
        "response_status": "completed",
        "empty": False,
        "malformed": False,
    }

    def handle(request):
        body = json.loads(request.content)
        state["requests"].append(body)
        if state["http_status"] != 200:
            return httpx.Response(
                state["http_status"], json={"error": {"message": "secret-provider-body"}}
            )
        payload = json.loads(body["input"])
        answered = payload["candidate"]["status"] == "answered"
        verdict = {
            name: {"score": 2 if applies else None, "rationale": "Synthetic fixture assessment."}
            for name, applies in {
                "answer_correctness": payload["expected_status"] == "answered",
                "faithfulness": answered,
                "citation_support": answered,
                "response_appropriateness": True,
            }.items()
        }
        if state["override"] is not None:
            verdict = state["override"]
        output = []
        if not state["empty"]:
            output = [
                {
                    "id": "msg_judge",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "annotations": [],
                            "text": "not json" if state["malformed"] else json.dumps(verdict),
                        }
                    ],
                }
            ]
        return httpx.Response(
            200,
            headers={"x-request-id": "req_judge"},
            json={
                "id": "resp_judge",
                "object": "response",
                "created_at": 0,
                "status": state["response_status"],
                "model": body["model"],
                "output": output,
                "usage": {
                    "input_tokens": 200,
                    "output_tokens": 40,
                    "total_tokens": 240,
                    "input_tokens_details": {"cached_tokens": 30},
                    "output_tokens_details": {"reasoning_tokens": 10},
                },
            },
        )

    with OpenAI(
        api_key="test-only",
        base_url="https://api.openai.test/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    ) as client:
        yield client, state


@pytest.fixture
def make_run(
    tmp_path,
    monkeypatch,
    dataset_bundle,
    baseline_settings,
    judge_settings,
    judge_client,
    make_answer,
):
    _, cases, _, _ = dataset_bundle
    by_question = {case.question: case for case in cases}
    monkeypatch.setattr("support_copilot.evaluation.runner.verify_database", lambda *_: None)
    monkeypatch.setattr(
        "support_copilot.evaluation.runner.answer_question",
        lambda question, settings, url, client, request_id: make_answer(
            by_question[question], request_id
        ),
    )
    sdk, _ = judge_client

    def run(name, limit=3, split="dev", settings=None):
        output = tmp_path / name
        result = run_evaluation(
            DATASET,
            SNAPSHOT,
            output,
            split,
            limit,
            settings or baseline_settings,
            judge_settings,
            "test-not-a-database",
            sdk,
            sdk,
        )
        return output, result

    return run
