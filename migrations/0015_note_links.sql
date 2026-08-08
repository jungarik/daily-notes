-- 0015_note_links: directed connections between notes (Zettelkasten links).
-- Backlinks are the reverse query. Links are curated by the user (source='user');
-- kind/source leave room for typed/LLM-suggested links later.

CREATE TABLE IF NOT EXISTS note_links (
    id            SERIAL PRIMARY KEY,
    from_note_id  INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    to_note_id    INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL DEFAULT 'related',
    source        TEXT NOT NULL DEFAULT 'user',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (from_note_id, to_note_id),
    CHECK (from_note_id <> to_note_id)
);

CREATE INDEX IF NOT EXISTS idx_note_links_from ON note_links (from_note_id);
CREATE INDEX IF NOT EXISTS idx_note_links_to   ON note_links (to_note_id);
