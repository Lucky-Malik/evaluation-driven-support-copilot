ALTER TABLE chunks ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('pg_catalog.english', section), 'A') ||
    setweight(to_tsvector('pg_catalog.english', content), 'B')
) STORED;
CREATE INDEX chunks_search_gin ON chunks USING gin (search_vector);

ALTER TABLE schema_version DROP CONSTRAINT schema_version_version_check;
UPDATE schema_version SET version = 3;
ALTER TABLE schema_version ADD CONSTRAINT schema_version_version_check CHECK (version = 3);
