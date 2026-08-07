-- 0013_decouple_user: separate the note model from the Telegram interface.
-- A user has a surrogate id and an OPTIONAL chat_id (Telegram); notes can come
-- from other UIs too. messages/reminders are keyed on user_id; the Telegram
-- layer resolves chat_id <-> user_id at the edge.

CREATE TABLE IF NOT EXISTS users (
    id          BIGSERIAL PRIMARY KEY,
    chat_id     BIGINT UNIQUE,           -- Telegram chat, optional
    timezone    TEXT,
    language    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Migrate existing per-chat settings, and ensure every chat that has data
-- gets a user row.
INSERT INTO users (chat_id, timezone, language)
SELECT chat_id, timezone, language FROM user_settings
ON CONFLICT (chat_id) DO NOTHING;
INSERT INTO users (chat_id) SELECT DISTINCT chat_id FROM messages
ON CONFLICT (chat_id) DO NOTHING;
INSERT INTO users (chat_id) SELECT DISTINCT chat_id FROM reminders
ON CONFLICT (chat_id) DO NOTHING;

-- messages: chat_id -> user_id
ALTER TABLE messages ADD COLUMN user_id BIGINT REFERENCES users(id) ON DELETE CASCADE;
UPDATE messages m SET user_id = u.id FROM users u WHERE u.chat_id = m.chat_id;
DROP INDEX IF EXISTS idx_messages_note_type;
DROP INDEX IF EXISTS idx_messages_path;
ALTER TABLE messages DROP COLUMN chat_id;
ALTER TABLE messages ALTER COLUMN user_id SET NOT NULL;
CREATE INDEX idx_messages_user_type ON messages (user_id, note_type);
CREATE INDEX idx_messages_user_path ON messages (user_id, path);

-- reminders: chat_id -> user_id
ALTER TABLE reminders ADD COLUMN user_id BIGINT REFERENCES users(id) ON DELETE CASCADE;
UPDATE reminders r SET user_id = u.id FROM users u WHERE u.chat_id = r.chat_id;
ALTER TABLE reminders DROP COLUMN chat_id;
ALTER TABLE reminders ALTER COLUMN user_id SET NOT NULL;

DROP TABLE user_settings;
