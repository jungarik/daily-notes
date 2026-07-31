-- 0004_reminders: reminders parsed from messages.
-- A reminder belongs to the message it was parsed from (message_id FK) and moves
-- through a small set of statuses. The partial index keeps the dispatcher's
-- "what's due now" query cheap by only indexing rows that can still fire.

CREATE TABLE IF NOT EXISTS reminders (
    id          SERIAL PRIMARY KEY,
    message_id  INTEGER REFERENCES messages(id) ON DELETE CASCADE,
    chat_id     BIGINT NOT NULL,
    remind_at   TIMESTAMPTZ NOT NULL,
    text        TEXT NOT NULL,
    -- 'sending' is a transient status a row is claimed into while it's being
    -- delivered, so concurrent dispatchers never grab the same reminder twice.
    status      TEXT NOT NULL DEFAULT 'scheduled'
                CHECK (status IN ('scheduled', 'postponed', 'sending', 'done', 'canceled')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reminders_due
    ON reminders (remind_at)
    WHERE status IN ('scheduled', 'postponed');
