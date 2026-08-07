-- 0014_rename_notes: the domain entity is a "note", not a Telegram "message".
-- Rename messages -> notes, message_chunks -> note_chunks, message_id -> note_id.

ALTER TABLE messages RENAME TO notes;
ALTER TABLE message_chunks RENAME TO note_chunks;
ALTER TABLE note_chunks RENAME COLUMN message_id TO note_id;
ALTER TABLE reminders RENAME COLUMN message_id TO note_id;

ALTER INDEX IF EXISTS idx_messages_user_type RENAME TO idx_notes_user_type;
ALTER INDEX IF EXISTS idx_messages_user_path RENAME TO idx_notes_user_path;
ALTER INDEX IF EXISTS idx_messages_tags RENAME TO idx_notes_tags;
ALTER INDEX IF EXISTS idx_message_chunks_message_id RENAME TO idx_note_chunks_note_id;
ALTER INDEX IF EXISTS idx_message_chunks_embedding RENAME TO idx_note_chunks_embedding;
