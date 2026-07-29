-- 0001_init: base schema for the notes bot.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS messages (
    id          SERIAL PRIMARY KEY,
    chat_id     BIGINT NOT NULL,
    username    TEXT,
    text        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
