-- 0010_drop_audio_url: only the object key is kept on the message; the public
-- URL is derived on demand when needed, not stored.

ALTER TABLE messages DROP COLUMN IF EXISTS audio_url;
