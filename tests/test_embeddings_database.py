from importlib.resources import files

import pytest
from fastapi.testclient import TestClient
from openai import InternalServerError

from support_copilot import db
from support_copilot.app import app
from support_copilot.retrieval import corpus_status, embed_corpus, retrieve
from support_copilot.snapshot import load_snapshot

pytestmark = pytest.mark.integration


@pytest.fixture
def indexed_settings(isolated_db, snapshot, baseline_settings):
    db.initialize(isolated_db)
    db.ingest(isolated_db, snapshot)
    manifest, _ = load_snapshot(snapshot)
    return baseline_settings.model_copy(
        update={"snapshot_id": manifest.snapshot_id, "embedding_batch_size": 5}
    )


def test_phase1_upgrade_preserves_existing_corpus(isolated_db, snapshot):
    with db.connect(isolated_db) as connection:
        connection.execute(files("support_copilot").joinpath("schema.sql").read_text())
    db.ingest(isolated_db, snapshot)
    with db.connect(isolated_db) as connection:
        before = connection.execute("SELECT id, content_sha256 FROM chunks ORDER BY id").fetchall()
    db.initialize(isolated_db)
    db.initialize(isolated_db)
    db.check_ready(isolated_db)
    with db.connect(isolated_db) as connection:
        assert connection.execute("SELECT version FROM schema_version").fetchone() == (2,)
        assert (
            connection.execute("SELECT id, content_sha256 FROM chunks ORDER BY id").fetchall()
            == before
        )
        assert connection.execute("SELECT count(*) FROM chunk_embeddings").fetchone() == (0,)


def test_embedding_reuse_and_reingestion_preserve_vectors(
    isolated_db, indexed_settings, snapshot, provider_client
):
    client, state = provider_client
    first = embed_corpus(isolated_db, indexed_settings, client)
    assert first["new_embeddings"] == 12
    assert first["ready"] is True
    assert len(first["provider_calls"]) == 3
    with db.connect(isolated_db) as connection:
        before = connection.execute("SELECT * FROM chunk_embeddings ORDER BY chunk_id").fetchall()
    db.ingest(isolated_db, snapshot)
    second = embed_corpus(isolated_db, indexed_settings, client)
    assert second["new_embeddings"] == 0
    assert len(state["calls"]) == 3
    with db.connect(isolated_db) as connection:
        assert (
            connection.execute("SELECT * FROM chunk_embeddings ORDER BY chunk_id").fetchall()
            == before
        )


def test_failed_batch_resumes_and_partial_index_is_not_ready(
    isolated_db, indexed_settings, provider_client
):
    client, state = provider_client
    state["fail_embedding_after"] = 1
    with pytest.raises(InternalServerError):
        embed_corpus(isolated_db, indexed_settings, client)
    partial = corpus_status(isolated_db, indexed_settings)
    assert partial["embedded_chunks"] == 5
    assert partial["ready"] is False
    state["fail_embedding_after"] = None
    result = embed_corpus(isolated_db, indexed_settings, client)
    assert result["new_embeddings"] == 7
    assert result["embedded_chunks"] == 12
    assert result["ready"] is True


def test_cosine_order_and_model_isolation(isolated_db, indexed_settings, provider_client):
    client, _ = provider_client
    embed_corpus(isolated_db, indexed_settings, client)
    with db.connect(isolated_db) as connection:
        ids = [row[0] for row in connection.execute("SELECT id FROM chunks ORDER BY id").fetchall()]
        connection.execute("UPDATE chunk_embeddings SET embedding = '[0,1,0]'::public.vector")
        connection.execute(
            "UPDATE chunk_embeddings SET embedding = '[1,0,0]'::public.vector WHERE chunk_id = %s",
            (ids[-1],),
        )
        connection.execute(
            "UPDATE chunk_embeddings SET embedding = '[1,1,0]'::public.vector WHERE chunk_id = %s",
            (ids[0],),
        )
    result = retrieve(isolated_db, [1, 0, 0], indexed_settings.model_copy(update={"top_k": 3}))
    assert result[0].chunk_id == ids[-1]
    assert result[0].cosine_distance == pytest.approx(0)
    assert result[1].chunk_id == ids[0]
    assert result[1].cosine_distance == pytest.approx(1 - 2**-0.5)
    assert result[2].cosine_distance == pytest.approx(1)
    assert result[0].source_url.startswith("https://fastapi.tiangolo.com/")
    other_model = indexed_settings.model_copy(update={"embedding_model": "different-model"})
    assert retrieve(isolated_db, [1, 0, 0], other_model) == []
    assert corpus_status(isolated_db, other_model)["ready"] is False
    other_dimension = indexed_settings.model_copy(update={"embedding_dimensions": 2})
    assert retrieve(isolated_db, [1, 0], other_dimension) == []


def test_stale_content_hash_is_excluded_and_repaired(
    isolated_db, indexed_settings, provider_client
):
    client, _ = provider_client
    embed_corpus(isolated_db, indexed_settings, client)
    with db.connect(isolated_db) as connection:
        connection.execute("UPDATE chunk_embeddings SET content_sha256 = %s", ("0" * 64,))
    assert corpus_status(isolated_db, indexed_settings)["ready"] is False
    assert retrieve(isolated_db, [1, 0, 0], indexed_settings) == []
    result = embed_corpus(isolated_db, indexed_settings, client)
    assert result["new_embeddings"] == 12
    assert result["ready"] is True


def test_http_flow_with_real_database_and_mock_provider(
    isolated_db,
    indexed_settings,
    provider_client,
    monkeypatch,
):
    sdk, state = provider_client
    embed_corpus(isolated_db, indexed_settings, sdk)
    monkeypatch.setattr("support_copilot.app.OpenAI", lambda **_: sdk)
    monkeypatch.setattr("support_copilot.app.api_key", lambda: "test-only")
    monkeypatch.setattr("support_copilot.app.database_url", lambda: isolated_db)
    monkeypatch.setattr("support_copilot.app.load_settings", lambda: indexed_settings)
    with TestClient(app) as http:
        response = http.post("/ask", json={"question": "A synthetic integration-test question"})
    assert response.status_code == 200
    answer = response.json()
    assert len(answer["retrieved_passages"]) == indexed_settings.top_k
    assert answer["trace"]["snapshot_id"] == indexed_settings.snapshot_id
    assert answer["citations"][0]["chunk_id"] in {
        p["chunk_id"] for p in answer["retrieved_passages"]
    }
    assert len(state["calls"]) == 5
