# Agentic enrichment / note actions

Status: **implemented.** Enrich owns confirmed writes over notes: creating and
moving them, enriching metadata, and curating links. Scheduling is a separate
agent — see `devdoc/agentic-reminder.md`. The loop routes a turn here; this
file is what the agent does once it has been routed to.

## Workflow

`agents/enricher/graph.py` defines `ENRICH_GRAPH`, a bounded LangGraph workflow.
Every node is a module with a single public `run`: the flat loop primitives
`reason`/`act`/`plan`/`approve`, and the phase subpackages `classify/` and
`write/`. Read tools (`get_note_context`, `list_paths`,
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
classify_propose -> classify_normalize` nodes. The graph then presents the exact normalized action at the
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

`agent.py` plans with the stateless `ACTION_PLAN_GRAPH`. Its planning flow (`plan` + `act`) may inspect referenced notes, paths, and tags.
Metadata requests use the same three classify nodes before `validate_write`, so
the returned `{name,args,summary}` contains the proposed title, type, path, tags,
and priority. `set_reminder` is not served here at all — it is the reminder
agent's (`agents/reminder/`). Note-targeting writes
are checked against the current user. Planning never executes a write.

The planner is given the instruction plus whatever context the turn carried —
recent conversation, ordered referenced note ids, citations, resolved entities,
locale, timezone and request time — so it can resolve phrases such as “that
note” without guessing from an isolated sentence. The loop passes these as
`AgentRequest.references`; `agent.py` maps them into the planning request.

## Layers and public API

- `tools/`: schemas, handlers, and human confirmation summaries.
- `graph.py` + `nodes/classify/`: reusable metadata proposal workflow.
- `domain.py`: deterministic note chunking, normalization, reminder proposal
  assembly, and persistence.
- The agent owns no SQL. Every read and write goes through `tools/enricher/`
  (`tools/enricher/db.py`); `plan_action` hydrates referenced notes with the
  `get_note_context` tool rather than querying. Thread state belongs to the
  calling section, as `api/chat_v2` does.
- `agent.py`: the whole agent. `start` maps the loop's envelope into a
  `PlanRequest`, drives `ACTION_PLAN_GRAPH`, and pauses the turn with
  `needs_input`; `resume` performs the approved write through the tool and
  reports what it made as typed `Ref`s. `SPEC` is the package's only export.

The agent is client-agnostic and imports only shared infrastructure. Note
creation is text-only. Telegram keeps fast capture and its deferred Enrich
button; it does not call this agent for that flow.

Config: `ENRICH_AGENT_MODEL` and `ENRICH_AGENT_MAX_STEPS`.

## Removed: the standalone fast-capture flow

`capture_api.py` (`propose_capture` / `revise_capture` / `confirm_capture` /
`cancel_capture`) was built for a UI that never called it, and was deleted along
with its `CaptureProposal`/`RelatedNote` contracts and
`db.save_captured_thought`. The loop is the only way into this agent.
If a capture surface is wanted later, build it against the endpoint that needs
it rather than restoring a speculative API.
