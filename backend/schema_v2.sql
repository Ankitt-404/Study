CREATE TABLE IF NOT EXISTS documents (
    id          SERIAL PRIMARY KEY,
    owner_id    TEXT NOT NULL DEFAULT 'local',
    title       TEXT NOT NULL,
    filename    TEXT,
    sha256      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'queued',  -- queued, processing, ready, failed
    error       TEXT,
    page_count  INT,
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_id, sha256)
);

DROP TABLE IF EXISTS chunks;

CREATE TABLE chunks (
    id              SERIAL PRIMARY KEY,
    document_id     INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     INT NOT NULL,
    section_path    TEXT,
    page_start      INT,
    page_end        INT,
    content         TEXT NOT NULL,
    embedding       vector(384) NOT NULL,
    embedding_model TEXT NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}',
    content_tsv     tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);

CREATE INDEX chunks_document_idx ON chunks (document_id);
CREATE INDEX chunks_tsv_idx ON chunks USING GIN (content_tsv);