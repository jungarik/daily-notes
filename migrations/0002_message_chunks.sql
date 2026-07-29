-- 0002_message_chunks: normalized chunks of a message note.
-- One message can have many chunks (1:N via message_id FK). Each chunk carries
-- its own embedding and free-form metadata so text can be split, enriched, and
-- searched at chunk granularity.

CREATE TABLE IF NOT EXISTS message_chunks (
    id           SERIAL PRIMARY KEY,
    message_id   INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    chunk_index  INTEGER NOT NULL,             -- order of the chunk within its message
    content      TEXT NOT NULL,                -- normalized chunk text
    token_count  INTEGER,                      -- optional: tokens in this chunk
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,  -- arbitrary chunk metadata
    embedding    vector(1536),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (message_id, chunk_index)
);

-- Fast lookup of all chunks belonging to a message.
CREATE INDEX IF NOT EXISTS idx_message_chunks_message_id
    ON message_chunks (message_id);

-- Approximate-nearest-neighbour index for semantic search over chunks.
CREATE INDEX IF NOT EXISTS idx_message_chunks_embedding
    ON message_chunks USING hnsw (embedding vector_cosine_ops);
