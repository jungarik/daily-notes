-- Immutable evaluation runs/results sourced from existing conversation turns.

CREATE TABLE IF NOT EXISTS eval_runs (
    id                  BIGSERIAL PRIMARY KEY,
    requested_by_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id           INTEGER NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
    turn_index          INTEGER NOT NULL CHECK (turn_index > 0),
    agent_filter        TEXT NOT NULL CHECK (agent_filter IN ('chat', 'enrich', 'reminder')),
    expected_behavior   TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    judge_enabled       BOOLEAN NOT NULL,
    total_cases         INTEGER NOT NULL DEFAULT 0,
    error               TEXT,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS eval_results (
    id                  BIGSERIAL PRIMARY KEY,
    run_id              BIGINT NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    thread_id           INTEGER NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
    turn_index          INTEGER NOT NULL CHECK (turn_index > 0),
    agent               TEXT NOT NULL CHECK (agent IN ('chat', 'enrich', 'reminder')),
    question            TEXT NOT NULL,
    expected_behavior   TEXT NOT NULL,
    answer              TEXT NOT NULL DEFAULT '',
    retrieved_chunks    TEXT NOT NULL DEFAULT '',
    route_or_mode       TEXT NOT NULL DEFAULT 'fallback',
    tools_used          TEXT NOT NULL DEFAULT '',
    task_success        TEXT CHECK (task_success IN ('yes', 'partial', 'no')),
    groundedness        TEXT CHECK (groundedness IN ('good', 'partial', 'bad')),
    answer_quality      TEXT CHECK (answer_quality IN ('good', 'partial', 'bad')),
    latency_ms          INTEGER NOT NULL CHECK (latency_ms >= 0),
    errors              TEXT NOT NULL DEFAULT 'none',
    notes               TEXT NOT NULL DEFAULT '',
    trace               JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_eval_runs_requester_started
    ON eval_runs (requested_by_user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_eval_runs_thread_turn
    ON eval_runs (thread_id, turn_index, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_eval_results_run_agent
    ON eval_results (run_id, agent, id);
CREATE INDEX IF NOT EXISTS idx_eval_results_thread_turn
    ON eval_results (thread_id, turn_index, created_at DESC);
