-- 0009_audio_url: store the public URL of the voice audio alongside its key.

ALTER TABLE messages ADD COLUMN IF NOT EXISTS audio_url TEXT;
