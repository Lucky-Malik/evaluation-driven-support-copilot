import pytest
from pydantic import ValidationError

from support_copilot.retrieval import reciprocal_rank_fusion
from support_copilot.settings import Settings, config_hash, load_settings


def test_rrf_hand_calculation_and_distinct_candidate_union(passage):
    a = passage.model_copy(update={"chunk_id": "a"})
    b = passage.model_copy(update={"chunk_id": "b"})
    c = passage.model_copy(update={"chunk_id": "c", "cosine_distance": None, "keyword_score": 9})
    results = reciprocal_rank_fusion([a, b], [b, c], 60, 3)
    assert [p.chunk_id for p in results] == ["b", "a", "c"]
    assert results[0].rrf_score == pytest.approx(1 / 62 + 1 / 61)
    assert results[0].vector_rank == 2
    assert results[0].keyword_rank == 1
    assert results[2].cosine_distance is None
    assert results[2].keyword_score == 9
    assert a.rrf_score is None


def test_rrf_ties_duplicates_empty_lists_and_limit(passage):
    a = passage.model_copy(update={"chunk_id": "a"})
    b = passage.model_copy(update={"chunk_id": "b"})
    assert [p.chunk_id for p in reciprocal_rank_fusion([b], [a], 60, 1)] == ["a"]
    assert reciprocal_rank_fusion([a, a], [], 60, 5)[0].rrf_score == pytest.approx(1 / 61)
    assert reciprocal_rank_fusion([], [], 60, 5) == []
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([], [], 0, 5)


def test_retrieval_configuration_is_validated_and_fingerprinted(baseline_settings, monkeypatch):
    data = baseline_settings.model_dump()
    data.update(retrieval_mode="hybrid", candidate_k=2, top_k=5)
    with pytest.raises(ValidationError):
        Settings.model_validate(data)
    monkeypatch.setenv("COPILOT_RETRIEVAL_MODE", "hybrid")
    monkeypatch.setenv("COPILOT_SECTION_FILTER", "Dependencies")
    hybrid = load_settings()
    assert hybrid.pipeline_version == "hybrid-retrieval-v1"
    assert hybrid.section_filter == "Dependencies"
    assert config_hash(hybrid) != config_hash(baseline_settings)
