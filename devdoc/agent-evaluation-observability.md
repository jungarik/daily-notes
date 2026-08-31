# Agent evaluation and observability

Status: **thread-based evaluation implemented.** There is no persistent
`eval_cases` table in the final schema. An administrator selects an existing
conversation thread, optional completed turn, agent mode, and expected behavior.

## Data model

- `eval_runs`: requester, source `thread_id`, one-based `turn_index`, selected
  agent, expected behavior, judge flag, status, and timing.
- `eval_results`: source thread/turn, question or extracted handoff instruction,
  actual replay answer, evidence, route, tools, grades, latency, errors, notes,
  and structured JSONB trace.

Migration `0020_agent_evaluations.sql` creates only the final thread-based
`eval_runs` and `eval_results` schema; it has no case table or case dependency.

## Turn selection and replay

Turn indices are one-based among user messages. If omitted, evaluation selects
the latest completed turn. A turn is complete only after a final textual
assistant answer; a handoff still waiting for confirmation is not complete.

- `chat`: replays Chat over the original history up to the selected user message.
- `enrich`: extracts that turn's `perform_action` instruction and runs planning.
- `reminder`: extracts that turn's `set_reminder` instruction and runs planning.

Specialist evaluation requires the matching handoff in the selected turn. Replay
never persists a thread or approves a write. Traces capture tools, routes, and
bounded retrieved chunks. Latency excludes the judge call.

## Judge, API, and Telegram

`AGENT_EVAL_JUDGE_ENABLED=true` enables structured LLM grading. When disabled,
runtime observations remain populated while qualitative grades/rates are null.

Internal-token-protected endpoints:

- `POST /api/evals/run`: `{thread_id, turn_index?, agent, expected_behavior}`
- `GET /api/evals/metrics?run_id=&agent=`

Hidden Telegram commands are allowlisted by `EVAL_ADMIN_TELEGRAM_IDS`:

```text
/eval <thread_id> [turn_index] [chat|enrich|reminder] <expected behavior>
/eval_metrics [run_id] [chat|enrich|reminder]
```

Examples:

```text
/eval 42 Answer only from notes about sleep
/eval 42 3 reminder Resolve tomorrow at 09:00 and propose confirmation
/eval 42 enrich Propose the correct non-reminder note action
```

Other config: `AGENT_EVAL_JUDGE_MODEL` and
`AGENT_EVAL_API_TIMEOUT_SECONDS`.
