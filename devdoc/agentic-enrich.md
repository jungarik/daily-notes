# Agentic enrichment / note actions

Status: **implemented.** Enrich owns non-reminder note writes: create a text
note, move a note to a validated vault path, and classify/enrich note metadata.
Reminder interpretation and creation belong to `agents/reminder`.

## Workflow

`agents/enrich/loop.py` defines `ENRICH_GRAPH`, a bounded LangGraph
single-tool-call workflow. Read tools (`get_note_context`, `list_paths`, `list_tags`) loop to the
model. Write tools (`create_note`, `set_note_path`, `enrich_note`) route to
`pending_write` and then the durable `approval` interrupt. The confirm endpoint
resumes approval or decline, then returns to the model. `final` is the bounded fallback.

The stateless `ACTION_PLAN_GRAPH` supports Chat's `perform_action` handoff. Its
`plan_model -> plan_read -> validate_write` flow may inspect referenced notes,
paths, and tags before it returns `{name,args,summary}`. Note-targeting writes
are checked against the current user. Planning never executes a write.

Chat sends a typed handoff containing the instruction, recent conversation,
ordered referenced note ids, citations, recent tool results, resolved entities,
locale, timezone, and request time. This lets the planner resolve phrases such
as “that note” without guessing from an isolated sentence.

## Layers and public API

- `tools.py`: schemas, handlers, and human confirmation summaries.
- `domain.py`: note chunking/embedding, path validation, and one-shot enrichment.
- `db.py`: owner-scoped reads, note writes, metadata writes, and optional direct
  agent thread persistence.
- `service.py`: `start_turn` / `confirm` for a future direct surface, plus
  `plan_action` / `execute_action` used by Chat.

The agent is client-agnostic and imports only shared infrastructure. Note
creation is text-only. Telegram keeps fast capture and its deferred Enrich
button; it does not call this agent for that flow.

Config: `ENRICH_AGENT_MODEL` and `ENRICH_AGENT_MAX_STEPS`.
