import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from support_copilot import db
from support_copilot.corpus import sha256
from support_copilot.snapshot import SOURCE_URLS, Manifest, Page, fingerprint


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
