import os
from importlib.resources import files
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from support_copilot.corpus import (
    PIPELINE_VERSION,
    document_content,
    extract_html,
    make_chunks,
    sha256,
    stable_id,
)
from support_copilot.events import emit
from support_copilot.snapshot import load_snapshot


def database_url() -> str:
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL is required; copy .env.example to .env")
    return url


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, connect_timeout=3, options="-c statement_timeout=10000")


def initialize(url: str) -> None:
    schema = files("support_copilot").joinpath("schema.sql").read_text()
    with connect(url) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(710000)")
        exists = connection.execute("SELECT to_regclass('schema_version')").fetchone()[0]
        if exists is None:
            connection.execute(schema)
        version = connection.execute("SELECT version FROM schema_version").fetchall()
        if version == [(1,)]:
            migration = (
                files("support_copilot").joinpath("migrations/002_embeddings.sql").read_text()
            )
            connection.execute(migration)
            version = [(2,)]
        if version == [(2,)]:
            connection.execute(
                files("support_copilot").joinpath("migrations/003_keyword_search.sql").read_text()
            )
        elif version != [(3,)]:
            raise ValueError("Unsupported database schema version")
    emit("schema_initialized", version=3)


def check_ready(url: str) -> None:
    with connect(url) as connection:
        version = connection.execute("SELECT version FROM schema_version").fetchone()
        extension = connection.execute(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
        connection.execute("SELECT id, snapshot_id, pipeline_version FROM documents LIMIT 0")
        connection.execute(
            "SELECT id, document_id, content_sha256, search_vector FROM chunks LIMIT 0"
        )
        connection.execute("SELECT chunk_id, model, dimensions FROM chunk_embeddings LIMIT 0")
        if version != (3,) or extension != (1,):
            raise ValueError("Database schema or vector extension is not initialized")


def ingest(url: str, folder: Path) -> dict[str, str | int]:
    manifest, raw_pages = load_snapshot(folder)
    prepared = []
    for page, raw in zip(manifest.pages, raw_pages, strict=True):
        title, sections = extract_html(raw)
        if title != page.title:
            raise ValueError(f"Snapshot title mismatch: {page.file}")
        content = document_content(sections)
        document_id = stable_id(manifest.snapshot_id, page.source_url)
        prepared.append((page, document_id, content, make_chunks(document_id, sections)))
    with connect(url) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(710001)")
        for page, document_id, content, chunks in prepared:
            existing = connection.execute(
                "SELECT snapshot_hash, content_sha256, pipeline_version "
                "FROM documents WHERE id = %s",
                (document_id,),
            ).fetchone()
            content_hash = sha256(content.encode())
            if existing and existing != (manifest.snapshot_hash, content_hash, PIPELINE_VERSION):
                raise ValueError("Existing snapshot has different content or pipeline version")
            connection.execute(
                """INSERT INTO documents
                   (id, snapshot_id, snapshot_hash, source_url, title, captured_at, raw_sha256,
                    content_sha256, pipeline_version, content)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO NOTHING""",
                (
                    document_id,
                    manifest.snapshot_id,
                    manifest.snapshot_hash,
                    page.source_url,
                    page.title,
                    manifest.captured_at,
                    page.raw_sha256,
                    content_hash,
                    PIPELINE_VERSION,
                    content,
                ),
            )
            connection.execute(
                "DELETE FROM chunks WHERE document_id = %s AND NOT (id = ANY(%s))",
                (document_id, [chunk.id for chunk in chunks]),
            )
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO chunks
                       (id, document_id, ordinal, section, anchor, content, content_sha256)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (id) DO UPDATE SET
                       ordinal = EXCLUDED.ordinal, section = EXCLUDED.section,
                       anchor = EXCLUDED.anchor, content = EXCLUDED.content,
                       content_sha256 = EXCLUDED.content_sha256""",
                    [
                        (
                            chunk.id,
                            document_id,
                            chunk.ordinal,
                            chunk.section,
                            chunk.anchor,
                            chunk.content,
                            chunk.content_sha256,
                        )
                        for chunk in chunks
                    ],
                )
    result = {
        "snapshot_id": manifest.snapshot_id,
        "documents": len(prepared),
        "chunks": sum(len(chunks) for _, _, _, chunks in prepared),
    }
    emit("ingestion_completed", **result)
    return result
