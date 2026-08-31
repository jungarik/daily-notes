CREATE TABLE IF NOT EXISTS action_executions (
    action_id UUID PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent TEXT NOT NULL CHECK (agent IN ('enrich', 'reminder')),
    action JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('executing', 'completed', 'failed')),
    result TEXT,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS action_executions_user_status_idx
    ON action_executions (user_id, status, created_at DESC);
