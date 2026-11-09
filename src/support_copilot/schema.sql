CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS schema_version (
    version integer PRIMARY KEY CHECK (version = 1)
);

CREATE TABLE IF NOT EXISTS documents (
    id text PRIMARY KEY,
    snapshot_id text NOT NULL,
    snapshot_hash text NOT NULL CHECK (length(snapshot_hash) = 64),
    source_url text NOT NULL,
    title text NOT NULL,
    captured_at timestamptz NOT NULL,
    raw_sha256 text NOT NULL CHECK (length(raw_sha256) = 64),
    content_sha256 text NOT NULL CHECK (length(content_sha256) = 64),
    pipeline_version text NOT NULL,
    content text NOT NULL CHECK (length(content) > 0),
    UNIQUE (snapshot_id, source_url)
);

CREATE TABLE IF NOT EXISTS chunks (
    id text PRIMARY KEY,
    document_id text NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    section text NOT NULL,
    anchor text NOT NULL,
    content text NOT NULL CHECK (length(content) > 0),
    content_sha256 text NOT NULL CHECK (length(content_sha256) = 64),
    UNIQUE (document_id, ordinal)
);

INSERT INTO schema_version (version) VALUES (1) ON CONFLICT DO NOTHING;
