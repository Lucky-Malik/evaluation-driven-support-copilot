CREATE TABLE chunk_embeddings (
    chunk_id text NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    model text NOT NULL,
    returned_model text,
    dimensions integer NOT NULL CHECK (dimensions BETWEEN 1 AND 2000),
    content_sha256 text NOT NULL CHECK (length(content_sha256) = 64),
    embedding public.vector NOT NULL,
    PRIMARY KEY (chunk_id, model, dimensions),
    CHECK (public.vector_dims(embedding) = dimensions),
    CHECK (public.vector_norm(embedding) > 0)
);

ALTER TABLE schema_version DROP CONSTRAINT schema_version_version_check;
UPDATE schema_version SET version = 2;
ALTER TABLE schema_version ADD CONSTRAINT schema_version_version_check CHECK (version = 2);
