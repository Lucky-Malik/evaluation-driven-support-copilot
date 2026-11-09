import pytest
from fastapi.testclient import TestClient

from support_copilot import db
from support_copilot.app import app

pytestmark = pytest.mark.integration


def records(url):
    with db.connect(url) as connection:
        documents = connection.execute("SELECT * FROM documents ORDER BY id").fetchall()
        chunks = connection.execute("SELECT * FROM chunks ORDER BY id").fetchall()
    return documents, chunks


def test_schema_readiness_and_idempotent_ingestion(isolated_db, snapshot, monkeypatch):
    monkeypatch.setattr("support_copilot.app.database_url", lambda: isolated_db)
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 503
        db.initialize(isolated_db)
        db.initialize(isolated_db)
        assert client.get("/ready").status_code == 200
    result = db.ingest(isolated_db, snapshot)
    before = records(isolated_db)
    assert result["documents"] == 6
    assert len(before[0]) == 6
    assert len(before[1]) == result["chunks"] == 12
    assert db.ingest(isolated_db, snapshot) == result
    assert records(isolated_db) == before
    with db.connect(isolated_db) as connection:
        row = connection.execute(
            """SELECT d.source_url, d.title, d.snapshot_id, c.section, c.anchor,
                      length(c.content_sha256)
               FROM chunks c JOIN documents d ON d.id = c.document_id
               WHERE c.anchor = 'example' LIMIT 1"""
        ).fetchone()
    assert row[0].startswith("https://fastapi.tiangolo.com/")
    assert row[1].startswith("Synthetic test page")
    assert row[2] == result["snapshot_id"]
    assert row[3].endswith(" > Example")
    assert row[4:] == ("example", 64)


def test_corrupt_snapshot_leaves_database_unchanged(isolated_db, snapshot):
    db.initialize(isolated_db)
    db.ingest(isolated_db, snapshot)
    before = records(isolated_db)
    (snapshot / "page-5.html").write_bytes(b"Corrupt file")
    with pytest.raises(ValueError, match="checksum mismatch"):
        db.ingest(isolated_db, snapshot)
    assert records(isolated_db) == before


def test_mid_ingestion_failure_rolls_back_all_documents(isolated_db, snapshot):
    db.initialize(isolated_db)
    with db.connect(isolated_db) as connection:
        connection.execute(
            """ALTER TABLE documents ADD CONSTRAINT simulated_failure
               CHECK (title != 'Synthetic test page 5')"""
        )
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        db.ingest(isolated_db, snapshot)
    assert records(isolated_db) == ([], [])
