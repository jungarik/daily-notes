-- 0003_voice: support voice messages.
-- A message can now originate from text or from a transcribed voice note. For
-- voice notes we also keep the original raw audio bytes and their MIME type.

ALTER TABLE messages ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'text';
ALTER TABLE messages ADD COLUMN IF NOT EXISTS audio       BYTEA;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS audio_mime  TEXT;
