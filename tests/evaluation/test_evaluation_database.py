from pathlib import Path

import pytest

from support_copilot import db
from support_copilot.errors import CopilotError
from support_copilot.evaluation.runner import verify_database
from support_copilot.retrieval import embed_corpus

pytestmark = pytest.mark.integration
SNAPSHOT = Path(__file__).resolve().parents[2] / "data/snapshots/fastapi-d4f83a093dd1b2ab"


def test_evaluation_requires_complete_index_and_exact_corpus(
    isolated_db,
    baseline_settings,
    provider_client,
    dataset_bundle,
):
    manifest, _, passages, _ = dataset_bundle
    db.initialize(isolated_db)
    db.ingest(isolated_db, SNAPSHOT)
    with pytest.raises(CopilotError, match="embed"):
        verify_database(isolated_db, baseline_settings, passages, manifest.snapshot_hash)
    sdk, _ = provider_client
    embed_corpus(isolated_db, baseline_settings, sdk)
    verify_database(isolated_db, baseline_settings, passages, manifest.snapshot_hash)
    with db.connect(isolated_db) as connection:
        connection.execute(
            "UPDATE chunks SET content = 'Tampered text' WHERE id = %s", (next(iter(passages)),)
        )
    with pytest.raises(ValueError, match="differs"):
        verify_database(isolated_db, baseline_settings, passages, manifest.snapshot_hash)
