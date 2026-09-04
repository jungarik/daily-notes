# Agentic enrichment / note actions

Status: **implemented.** Enrich owns every confirmed Chat write: creating and
moving notes, enriching metadata, and planning/creating reminders through
`agents/enrich/domain.py`.

## Workflow

`agents/enrich/graph.py` defines `ENRICH_GRAPH`, a bounded LangGraph workflow.
Every node is a module with a single public `run`: the flat loop primitives
`reason`/`act`/`plan`/`approve`, and the phase subpackages `classify/`,
`schedule/`, `write/`. Read tools (`get_note_context`, `list_paths`,
`list_tags`) loop through `act` back to `reason`. `create_note`, `set_note_path`,
and `add_note_tags` route to `stage`. `link_notes` is a *select* action and first
runs a dedicated `link_context` node (mirroring `enrich_note`'s classify phase):
retrieval — resolving the source note and computing its nearest neighbours —
lives there, not in the stage/validate nodes, which stay plain checks.
Retrieval recalls `LINK_RECALL_LIMIT` neighbours, then `write/_rank.py` reorders
them with one `LINK_RANK_LLM_MODEL` call by the *idea* each shares with the
source note — a principle, mechanism or tension carrying across both — so
conceptual links are offered ahead of merely same-topic notes; each candidate
carries the shared idea as `reason`, and the ranker's `idea_link` verdicts (up to
`LINK_PRESELECT_LIMIT`) become the preselection. Ranking degrades to plain
nearest-neighbour order on any model failure, and only then does the
`ENRICH_SIMILAR_MAX_DISTANCE` threshold preselect; when ranking ran and found no
real connection, nothing is preselected. `LINK_RANK_ENABLED=false` skips the pass.
`link_context` attaches `args.candidates` + a preselected `args.linked_note_ids`
so Chat can render a checklist; the user's picked ids are merged into the action
at approval time and inserted as directed `note_links` edges (read as
bidirectional). `enrich_note` first runs the explicit `classify_gather ->
classify_propose -> classify_normalize` nodes. `create_reminder` first runs
`schedule_resolve -> schedule_build`, so reminder time resolution is part of the
graph before approval. The graph then presents the exact normalized action at the
durable `approve` interrupt. Confirmation only persists those approved values; it
does not call an LLM. The confirm endpoint resumes approval or decline, then
returns to `reason` (which makes a tool-free answer once the step budget is spent
— the former `final` node folded in).

`classify_gather` contains no database or embedding implementation. It
deterministically invokes registered context tools: `get_note_context` when
needed, `list_paths`, `list_tags`, `get_vault_context`, and
`find_related_notes`. The node records their status and latency in
`metadata_trace`. The last two tools are internal workflow tools and are not
offered to the LLM in `TOOL_SPECS`.

The stateless `ACTION_PLAN_GRAPH` supports Chat's `perform_action` handoff. Its
planning flow (`plan` + `act`) may inspect referenced notes, paths, and tags.
Metadata requests use the same three classify nodes before `validate_write`, so
the returned `{name,args,summary}` contains the proposed title, type, path, tags,
and priority. `REMINDER_PLAN_GRAPH` supports Chat's `set_reminder` handoff with
the same explicit `schedule_resolve -> schedule_build` nodes. Note-targeting writes
are checked against the current user. Planning never executes a write.

Chat sends a typed handoff containing the instruction, recent conversation,
ordered referenced note ids, citations, recent tool results, resolved entities,
locale, timezone, and request time. This lets the planner resolve phrases such
as “that note” without guessing from an isolated sentence.

## Layers and public API

- `tools/`: schemas, handlers, and human confirmation summaries.
- `graph.py` + `nodes/classify/`: reusable metadata proposal workflow.
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
