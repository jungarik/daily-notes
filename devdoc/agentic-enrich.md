# Agentic enrichment / note actions

Status: **implemented.** Enrich owns every confirmed Chat write: creating and
moving notes, enriching metadata, and planning/creating reminders through
`agents/enrich/domain.py`.

## Workflow

`agents/enrich/graph.py` defines `ENRICH_GRAPH`, a bounded LangGraph workflow.
Read tools (`get_note_context`, `list_paths`, `list_tags`) loop to the model.
`create_note` and `set_note_path` route to `pending_write`. `enrich_note` first
runs the explicit `metadata_context -> metadata_model -> metadata_validation`
nodes. `create_reminder` first runs
`reminder_model -> reminder_validation`, so reminder time extraction is part of
the graph before approval. The graph then presents the exact normalized action
at the durable `approval` interrupt. Confirmation only persists those approved
values; it does not call an LLM. The confirm endpoint resumes approval or
decline, then returns to the model. `final` is the bounded fallback.

`metadata_context` contains no database or embedding implementation. It
deterministically invokes registered context tools: `get_note_context` when
needed, `list_paths`, `list_tags`, `get_vault_context`, and
`find_related_notes`. The node records their status and latency in
`metadata_trace`. The last two tools are internal workflow tools and are not
offered to the LLM in `TOOL_SPECS`.

The stateless `ACTION_PLAN_GRAPH` supports Chat's `perform_action` handoff. Its
planning flow may inspect referenced notes, paths, and tags. Metadata requests
use the same three metadata nodes before `validate_write`, so the returned
`{name,args,summary}` contains the proposed title, type, path, tags, and priority.
`REMINDER_PLAN_GRAPH` supports Chat's `set_reminder` handoff with the same
explicit `reminder_model -> reminder_validation` nodes. Note-targeting writes
are checked against the current user. Planning never executes a write.

Chat sends a typed handoff containing the instruction, recent conversation,
ordered referenced note ids, citations, recent tool results, resolved entities,
locale, timezone, and request time. This lets the planner resolve phrases such
as “that note” without guessing from an isolated sentence.

## Layers and public API

- `tools/`: schemas, handlers, and human confirmation summaries.
- `graph.py` + `nodes/metadata.py`: reusable metadata proposal workflow.
- `domain.py`: deterministic note chunking, normalization, reminder proposal
  assembly, and persistence.
- `db.py`: owner-scoped reads, note writes, metadata writes, and optional direct
  agent thread persistence.
- `api.py`: `start_turn` / `confirm` for a future direct surface, plus
  `plan_action` / `execute_action` used by Chat.

The agent is client-agnostic and imports only shared infrastructure. Note
creation is text-only. Telegram keeps fast capture and its deferred Enrich
button; it does not call this agent for that flow.

Config: `ENRICH_AGENT_MODEL` and `ENRICH_AGENT_MAX_STEPS`.
## Standalone fast capture

Enrich can be called without Conversation or an HTTP endpoint. A future UI,
Telegram adapter, or plugin can use `propose_capture`, show the returned title,
path, tags and related-note suggestions, then call `revise_capture`,
`confirm_capture`, or `cancel_capture`.

The proposal does not write data. Confirmation uses a stable `action_id`, and
the note, chunks, metadata, and selected links are committed in one database
transaction. Retrying the same confirmation reuses the execution-ledger result.
Capture and existing-note enrichment share the same metadata workflow and fallback
normalization.
