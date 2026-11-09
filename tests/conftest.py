import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
import pytest
from openai import OpenAI
from psycopg import sql

from support_copilot import db
from support_copilot.contracts import Passage
from support_copilot.corpus import sha256
from support_copilot.settings import load_settings
from support_copilot.snapshot import SOURCE_URLS, Manifest, Page, fingerprint


@pytest.fixture
def baseline_settings(monkeypatch):
    for field in ("GENERATION_MODEL", "EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS", "TOP_K"):
        monkeypatch.delenv(f"COPILOT_{field}", raising=False)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    return load_settings().model_copy(update={"embedding_dimensions": 3})


@pytest.fixture
def passage():
    return Passage(
        chunk_id="chunk-one",
        document_id="doc-one",
        source_url="https://fastapi.tiangolo.com/tutorial/path-params/#types",
        title="Path Parameters",
        section="Types",
        snapshot_id="test-snapshot",
        content_sha256="a" * 64,
        content="Declare item_id: int for integer validation.",
        cosine_distance=0.1,
    )


@pytest.fixture
def provider_client():
    state = {
        "calls": [],
        "status": "answered",
        "http_status": 200,
        "fail_endpoint": "/responses",
        "embedding_data": None,
        "citation_id": None,
        "response_status": "completed",
        "refusal": False,
        "invalid_draft": False,
        "fail_embedding_after": None,
        "embedding_calls": 0,
        "timeout": False,
    }

    def handle(request):
        body = json.loads(request.content)
        state["calls"].append((request.url.path, body))
        if state["timeout"] and request.url.path.endswith("/responses"):
            raise httpx.ReadTimeout("Sensitive synthetic provider detail", request=request)
        if request.url.path.endswith("/embeddings"):
            state["embedding_calls"] += 1
            fail_after = state["fail_embedding_after"]
            if fail_after is not None and state["embedding_calls"] > fail_after:
                return httpx.Response(500, json={"error": {"message": "secret provider details"}})
        if request.url.path.endswith(state["fail_endpoint"]) and state["http_status"] != 200:
            return httpx.Response(
                state["http_status"], json={"error": {"message": "sk-secret-body"}}
            )
        if request.url.path.endswith("/embeddings"):
            data = state["embedding_data"]
            if data is None:
                data = [
                    {
                        "index": index,
                        "object": "embedding",
                        "embedding": [1.0] + [0.0] * (body["dimensions"] - 1),
                    }
                    for index, _ in enumerate(body["input"])
                ]
            return httpx.Response(
                200,
                headers={"x-request-id": "req_embedding"},
                json={
                    "object": "list",
                    "model": body["model"],
                    "data": data,
                    "usage": {"prompt_tokens": 12, "total_tokens": 12},
                },
            )
        payload = json.loads(body["input"])
        status = state["status"]
        draft = {
            "status": status,
            "answer": None,
            "clarification_question": None,
            "citation_ids": [],
            "reason": "Scripted test decision, not an LLM assessment.",
        }
        if status == "answered":
            draft["answer"] = "Declare item_id: int for integer validation."
            draft["citation_ids"] = [state["citation_id"] or payload["evidence"][0]["chunk_id"]]
        elif status == "needs_clarification":
            draft["clarification_question"] = "Which request parameter needs validation?"
        if state["invalid_draft"]:
            draft["answer"] = None
            draft["citation_ids"] = []
            draft["status"] = "answered"
        content = {"type": "output_text", "text": json.dumps(draft), "annotations": []}
        if state["refusal"]:
            content = {"type": "refusal", "refusal": "Scripted provider refusal"}
        output = [
            {
                "type": "message",
                "id": "msg_test",
                "role": "assistant",
                "status": "completed",
                "content": [content],
            }
        ]
        if state["response_status"] != "completed":
            output = []
        return httpx.Response(
            200,
            headers={"x-request-id": "req_generation"},
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 0,
                "status": state["response_status"],
                "model": body["model"],
                "output": output,
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "input_tokens_details": {"cached_tokens": 10},
                    "output_tokens_details": {"reasoning_tokens": 5},
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
def snapshot(tmp_path: Path) -> Path:
    pages = []
    for index, url in enumerate(SOURCE_URLS):
        raw = (
            f'<article class="md-content__inner"><h1>Synthetic test page {index}</h1>'
            '<p>A paragraph for testing ingestion.</p><h2 id="example">Example</h2>'
            "<pre><code>def example():\n    return 42\n</code></pre></article>"
        ).encode()
        filename = f"page-{index}.html"
        (tmp_path / filename).write_bytes(raw)
        pages.append(
            Page(
                source_url=url,
                title=f"Synthetic test page {index}",
                file=filename,
                raw_sha256=sha256(raw),
            )
        )
    license_bytes = b"Synthetic test fixture license; not official documentation."
    (tmp_path / "LICENSE").write_bytes(license_bytes)
    digest = fingerprint(pages, sha256(license_bytes))
    manifest = Manifest(
        snapshot_id=f"fastapi-{digest[:16]}",
        snapshot_hash=digest,
        captured_at=datetime.now(UTC),
        license_sha256=sha256(license_bytes),
        pages=pages,
    )
    (tmp_path / "manifest.json").write_text(manifest.model_dump_json())
    return tmp_path


@pytest.fixture
def isolated_db(monkeypatch: pytest.MonkeyPatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    schema = f"test_{uuid4().hex}"
    with psycopg.connect(url) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    def connect_isolated(dsn: str) -> psycopg.Connection:
        return psycopg.connect(
            dsn, connect_timeout=3, options=f"-c search_path={schema} -c statement_timeout=10000"
        )

    monkeypatch.setattr(db, "connect", connect_isolated)
    try:
        yield url
    finally:
        with psycopg.connect(url) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
