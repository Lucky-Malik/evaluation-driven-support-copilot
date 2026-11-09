import json
from time import perf_counter

from openai import OpenAI

from support_copilot import db
from support_copilot.contracts import Cost, Passage
from support_copilot.errors import CopilotError
from support_copilot.events import emit
from support_copilot.provider import embed, validate_vector
from support_copilot.settings import Settings, config_hash


def corpus_status(url: str, settings: Settings) -> dict:
    with db.connect(url) as connection:
        row = connection.execute(
            """SELECT count(*), count(e.chunk_id), min(d.snapshot_hash)
               FROM chunks c JOIN documents d ON d.id = c.document_id
               LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id AND e.model = %s
                   AND e.dimensions = %s AND e.content_sha256 = c.content_sha256
               WHERE d.snapshot_id = %s""",
            (settings.embedding_model, settings.embedding_dimensions, settings.snapshot_id),
        ).fetchone()
    return {
        "snapshot_id": settings.snapshot_id,
        "snapshot_hash": row[2],
        "chunks": row[0],
        "embedded_chunks": row[1],
        "ready": row[0] > 0 and row[0] == row[1],
        "embedding_model": settings.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions,
    }


def embed_corpus(url: str, settings: Settings, client: OpenAI) -> dict:
    started = perf_counter()
    with db.connect(url) as connection:
        pending = connection.execute(
            """SELECT c.id, c.content, c.content_sha256
               FROM chunks c JOIN documents d ON d.id = c.document_id
               LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id AND e.model = %s
                   AND e.dimensions = %s AND e.content_sha256 = c.content_sha256
               WHERE d.snapshot_id = %s AND e.chunk_id IS NULL ORDER BY c.id""",
            (settings.embedding_model, settings.embedding_dimensions, settings.snapshot_id),
        ).fetchall()
    calls = []
    for start in range(0, len(pending), settings.embedding_batch_size):
        batch = pending[start : start + settings.embedding_batch_size]
        result = embed(client, [row[1] for row in batch], settings)
        calls.append(result.call.model_dump())
        with db.connect(url) as connection:
            connection.execute("SELECT pg_advisory_xact_lock(710001)")
            for (chunk_id, _, content_hash), vector in zip(batch, result.vectors, strict=True):
                current = connection.execute(
                    "SELECT content_sha256 FROM chunks WHERE id = %s",
                    (chunk_id,),
                ).fetchone()
                if current != (content_hash,):
                    raise CopilotError(
                        "corpus_changed", "Corpus changed during embedding. Retry indexing."
                    )
                connection.execute(
                    """INSERT INTO chunk_embeddings
                       (chunk_id, model, returned_model, dimensions, content_sha256, embedding)
                       VALUES (%s, %s, %s, %s, %s, %s::public.vector)
                       ON CONFLICT (chunk_id, model, dimensions) DO UPDATE SET
                       content_sha256 = EXCLUDED.content_sha256, embedding = EXCLUDED.embedding,
                       returned_model = EXCLUDED.returned_model""",
                    (
                        chunk_id,
                        settings.embedding_model,
                        result.call.returned_model,
                        settings.embedding_dimensions,
                        content_hash,
                        json.dumps(vector),
                    ),
                )
        emit(
            "embedding_batch_completed",
            snapshot_id=settings.snapshot_id,
            chunks=len(batch),
            model=settings.embedding_model,
            input_tokens=result.call.usage.input_tokens if result.call.usage else -1,
        )
    status = corpus_status(url, settings)
    if status["chunks"] == 0:
        raise CopilotError("corpus_missing", "Ingest the configured documentation snapshot first.")
    return {
        **status,
        "new_embeddings": len(pending),
        "provider_calls": calls,
        "config_sha256": config_hash(settings),
        "cost": Cost().model_dump(),
        "elapsed_ms": round((perf_counter() - started) * 1000, 3),
    }


def retrieve(url: str, vector: list[float], settings: Settings) -> list[Passage]:
    validate_vector(vector, settings.embedding_dimensions)
    with db.connect(url) as connection:
        rows = connection.execute(
            """SELECT c.id, c.document_id, d.source_url, d.title, c.section,
                      d.snapshot_id, c.content_sha256, c.content, c.anchor,
                      e.embedding OPERATOR(public.<=>) %s::public.vector AS distance
               FROM chunk_embeddings e JOIN chunks c ON c.id = e.chunk_id
               JOIN documents d ON d.id = c.document_id
               WHERE e.model = %s AND e.dimensions = %s AND d.snapshot_id = %s
                   AND e.content_sha256 = c.content_sha256
               ORDER BY distance, c.id LIMIT %s""",
            (
                json.dumps(vector),
                settings.embedding_model,
                settings.embedding_dimensions,
                settings.snapshot_id,
                settings.top_k,
            ),
        ).fetchall()
    return [
        Passage(
            chunk_id=row[0],
            document_id=row[1],
            source_url=row[2] + (f"#{row[8]}" if row[8] else ""),
            title=row[3],
            section=row[4],
            snapshot_id=row[5],
            content_sha256=row[6],
            content=row[7],
            cosine_distance=row[9],
        )
        for row in rows
    ]
