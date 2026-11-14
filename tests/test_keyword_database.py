from importlib.resources import files
from pathlib import Path

import pytest

from support_copilot import db
from support_copilot.evaluation.keyword import keyword_evaluation
from support_copilot.retrieval import (
    corpus_status,
    embed_corpus,
    hybrid_retrieve,
    keyword_retrieve,
    retrieve,
)

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data/snapshots/fastapi-d4f83a093dd1b2ab"


@pytest.fixture
def keyword_corpus(isolated_db, baseline_settings):
    db.initialize(isolated_db)
    db.ingest(isolated_db, SNAPSHOT)
    return baseline_settings.model_copy(update={"retrieval_mode": "keyword"})


def test_keyword_identifier_search_needs_no_embeddings(isolated_db, keyword_corpus):
    assert corpus_status(isolated_db, keyword_corpus)["ready"]
    results = keyword_retrieve(isolated_db, "RequestValidationError", keyword_corpus)
    assert results
    assert all("RequestValidationError" in p.content for p in results)
    assert all(p.cosine_distance is None and p.keyword_score > 0 for p in results)
    assert keyword_retrieve(isolated_db, "the and is", keyword_corpus) == []
    assert keyword_retrieve(isolated_db, "zqxnonexistentidentifier", keyword_corpus) == []


def test_filters_apply_to_both_branches_before_fusion(isolated_db, keyword_corpus, provider_client):
    client, _ = provider_client
    embed_corpus(isolated_db, keyword_corpus, client)
    settings = keyword_corpus.model_copy(update={"section_filter": "RequestValidationError"})
    with db.connect(isolated_db) as connection:
        section = connection.execute(
            "SELECT section FROM chunks WHERE content LIKE '%RequestValidationError%' "
            "ORDER BY id LIMIT 1"
        ).fetchone()[0]
    settings = settings.model_copy(update={"section_filter": section})
    assert all(p.section == section for p in retrieve(isolated_db, [1, 0, 0], settings))
    keyword = keyword_retrieve(isolated_db, "RequestValidationError", settings)
    assert keyword and all(p.section == section for p in keyword)
    hybrid = hybrid_retrieve(isolated_db, "RequestValidationError", [1, 0, 0], settings)
    assert hybrid and all(p.section == section and p.rrf_score > 0 for p in hybrid)
    for changes in ({"snapshot_id": "absent"}, {"section_filter": "absent' OR 1=1 --"}):
        empty = settings.model_copy(update=changes)
        assert keyword_retrieve(isolated_db, "RequestValidationError", empty) == []
        assert hybrid_retrieve(isolated_db, "RequestValidationError", [1, 0, 0], empty) == []


def test_v2_migration_preserves_text_ids_and_vectors(
    isolated_db, baseline_settings, provider_client
):
    with db.connect(isolated_db) as connection:
        connection.execute(files("support_copilot").joinpath("schema.sql").read_text())
        connection.execute(
            files("support_copilot").joinpath("migrations/002_embeddings.sql").read_text()
        )
    db.ingest(isolated_db, SNAPSHOT)
    client, _ = provider_client
    embed_corpus(isolated_db, baseline_settings, client)
    with db.connect(isolated_db) as connection:
        before = connection.execute("SELECT * FROM chunk_embeddings ORDER BY chunk_id").fetchall()
        text_before = connection.execute("SELECT id, content FROM chunks ORDER BY id").fetchall()
    db.initialize(isolated_db)
    db.initialize(isolated_db)
    db.check_ready(isolated_db)
    with db.connect(isolated_db) as connection:
        assert (
            connection.execute("SELECT * FROM chunk_embeddings ORDER BY chunk_id").fetchall()
            == before
        )
        assert (
            connection.execute("SELECT id, content FROM chunks ORDER BY id").fetchall()
            == text_before
        )
        connection.execute(
            "UPDATE chunks SET content = 'uniquefreshkeyword' WHERE id = %s", (text_before[0][0],)
        )
    assert (
        keyword_retrieve(isolated_db, "uniquefreshkeyword", baseline_settings)[0].chunk_id
        == text_before[0][0]
    )


def test_free_keyword_report_uses_only_dev_cases(isolated_db, keyword_corpus, tmp_path):
    output = tmp_path / "keyword.json"
    result = keyword_evaluation(
        ROOT / "data/evaluation/fastapi-support-v1", SNAPSHOT, output, isolated_db, keyword_corpus
    )
    assert result["model_calls"] == 0
    assert result["overall"]["cases"] == 20
    assert result["overall"]["metrics"]["recall_at_k"]["n"] == 13
    # Phase 4 measured development baseline: keep this free CI gate reproducible.
    assert result["overall"]["metrics"]["recall_at_k"]["value"] >= 0.69
    assert result["overall"]["metrics"]["mrr_at_k"]["value"] >= 0.59
    with pytest.raises(ValueError, match="new report"):
        keyword_evaluation(
            ROOT / "data/evaluation/fastapi-support-v1",
            SNAPSHOT,
            output,
            isolated_db,
            keyword_corpus,
        )
