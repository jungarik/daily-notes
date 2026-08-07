-- 0012_note_path: replace the flat `projects` array with a single vault `path`
-- (the note's home folder, e.g. Projects/telegram-bot/architecture). One
-- canonical location per note maps directly onto an Obsidian folder tree;
-- cross-cutting membership stays in `tags`.

ALTER TABLE messages ADD COLUMN IF NOT EXISTS path TEXT;

-- Backfill: first existing project → a Projects/<project> path.
UPDATE messages
SET path = 'Projects/' || (projects->>0)
WHERE path IS NULL AND jsonb_typeof(projects) = 'array' AND jsonb_array_length(projects) > 0;

DROP INDEX IF EXISTS idx_messages_projects;
ALTER TABLE messages DROP COLUMN IF EXISTS projects;

CREATE INDEX IF NOT EXISTS idx_messages_path ON messages (chat_id, path);
