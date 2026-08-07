-- 0011_note_metadata: enrichment metadata for the brain-dump.
-- Each note is classified/tagged by an LLM at capture time.

ALTER TABLE messages ADD COLUMN IF NOT EXISTS note_type TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS title     TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS priority  TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS tags      JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS projects  JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS idx_messages_note_type ON messages (chat_id, note_type);
CREATE INDEX IF NOT EXISTS idx_messages_tags      ON messages USING gin (tags);
CREATE INDEX IF NOT EXISTS idx_messages_projects  ON messages USING gin (projects);
