CREATE TABLE IF NOT EXISTS agent_states (
    state_id UUID PRIMARY KEY,
    correlation_id UUID NOT NULL,
    causation_id UUID REFERENCES agent_states(state_id) ON DELETE SET NULL,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('done', 'needs_input', 'failed')),
    produced JSONB NOT NULL DEFAULT '[]'::jsonb,
    state JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_states_correlation_idx
    ON agent_states (correlation_id, created_at);

CREATE INDEX IF NOT EXISTS agent_states_user_idx
    ON agent_states (user_id, created_at DESC);

-- The broker now owns at-most-once execution, and its farm is open-ended: a new
-- agent is a registry entry, not a schema change. The old two-value CHECK would
-- reject the first ledger row written by any agent added after it.
ALTER TABLE action_executions
    DROP CONSTRAINT IF EXISTS action_executions_agent_check;
