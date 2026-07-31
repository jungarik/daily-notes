-- 0006_user_language: per-chat UI language.
-- Timezone becomes nullable so a user can set only a language (or vice versa)
-- without being forced to provide the other first.

ALTER TABLE user_settings ALTER COLUMN timezone DROP NOT NULL;
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS language TEXT;
