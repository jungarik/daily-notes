-- 0018_note_attachments: media files attached to a note (images for now; the
-- `kind` column leaves room for video/pdf/doc and, later, folding voice audio in
-- here too). Bytes live in object storage (S3-compatible); the row keeps only the
-- object key, mirroring how voice audio is stored. Multiple files per note, so a
-- one-to-many table rather than columns on `notes`.

CREATE TABLE IF NOT EXISTS note_attachments (
    id           SERIAL PRIMARY KEY,
    note_id      INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL DEFAULT 'image',   -- image | audio | video | pdf | doc
    storage_key  TEXT NOT NULL,                    -- object key in the bucket
    mime         TEXT,
    size_bytes   INTEGER,
    position     INTEGER NOT NULL DEFAULT 0,       -- carousel order within the note
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Listing a note's attachments in carousel order is the hot path.
CREATE INDEX IF NOT EXISTS idx_note_attachments_note
    ON note_attachments (note_id, position);
