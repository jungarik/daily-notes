-- Run manually if you prefer; bot.py also creates this automatically.
CREATE TABLE IF NOT EXISTS messages (
    id          SERIAL PRIMARY KEY,
    chat_id     BIGINT NOT NULL,
    username    TEXT,
    text        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
