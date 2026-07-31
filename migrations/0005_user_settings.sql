-- 0005_user_settings: per-chat preferences.
-- For now just the timezone, used to resolve reminder times like "tomorrow at 9"
-- against the user's own clock instead of a single server timezone.

CREATE TABLE IF NOT EXISTS user_settings (
    chat_id     BIGINT PRIMARY KEY,
    timezone    TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
