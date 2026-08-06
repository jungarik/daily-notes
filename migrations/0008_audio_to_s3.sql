-- 0008_audio_to_s3: voice audio now lives in object storage (S3-compatible),
-- not in the database. Drop the raw bytes column and keep only the object key.

ALTER TABLE messages DROP COLUMN IF EXISTS audio;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS audio_key TEXT;
