-- 0019_chat_threads: conversation state for the agentic chat tab.
-- `messages` is the running provider message list (assistant tool-calls + tool
-- results included) so a multi-turn thread — and a paused write awaiting the
-- user's confirmation (`pending`) — can be resumed on the next request.

CREATE TABLE IF NOT EXISTS chat_threads (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    messages    JSONB NOT NULL DEFAULT '[]'::jsonb,
    pending     JSONB,                       -- a write awaiting confirmation, or NULL
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_threads_user ON chat_threads (user_id, updated_at DESC);
