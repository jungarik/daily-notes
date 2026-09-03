# Agentic chat (Web App chat tab)

Status: **Q&A + specialist write handoffs.** Chat answers with owner-scoped read
tools and delegates writes to Enrich. Reminder handling is an Enrich capability.
Every write pauses for explicit confirmation; Chat never mutates data directly.

## Workflow and tools

`agents/conversation/graph.py` defines the bounded LangGraph `CHAT_GRAPH` — four
role-named nodes, each a module under `nodes/` exposing a single public `run`:
`reason`, `act`, `handoff`, `approve`. `reason` emits at most one tool call per
step (`parallel_tool_calls=False`), and conditional edges route it to:

- `act` for a read tool: `search_notes`, `get_note`, `neighbors`,
  `list_reminders`, `list_agenda`, `list_paths`, or `detect_reminder` (a
  deterministic reminder classifier the model can call cheaply, no model turn);
- `handoff` for a handoff tool — `perform_action(instruction)` (create/move/tag/
  link/enrich a note) or `set_reminder(instruction)` (schedule a reminder). One
  node picks the specialist from the tool name via `HANDOFF_SPECIALIST`;
- END when the model answers without a tool.

Read results loop back to `reason` until it answers or `AGENT_MAX_STEPS` is
used. `search_notes` returns structured evidence rather than calling another
LLM; `reason` produces the grounded answer on the next graph step. When the step
budget is spent, `reason` makes a final tool-free call so it must answer (this
replaced a separate `final` node). The former `pre_route` fast path is gone — the
model calls `detect_reminder` when it wants the cheap check.

## Specialist handoff and confirmation

1. The selected specialist runs `plan_action(...)` and returns
   `{name, args, summary}` without writing.
2. The graph checkpoints the proposal and pauses in `approval` with
   `interrupt(...)`. `chat_threads` receives a UI/evaluation projection, then
   the API returns `{status:"confirm", action}`.
3. `POST /api/chat/confirm` loads the same PostgreSQL checkpoint and sends
   `Command(resume=approve)`. Approval calls the recorded specialist's
   `execute_action(...)`; decline records a tool result without executing. The
   graph then returns to the model for acknowledgement.

Recording `pending.agent` makes resume deterministic. Older pending checkpoints
without that field default to Enrich for backward compatibility. Only one action
may be pending at a time.

### Select actions (pick-which confirmations)

Most actions confirm with a plain yes/no. A proposal can instead ask the user to
*choose* — the action carries `kind:"select"` (default `"confirm"`). `link_notes`
uses this: `plan_action` resolves the source note, computes its nearest semantic
neighbours, and puts `args.candidates` (`{note_id,title,path,tags,distance}`) plus
a preselected `args.linked_note_ids` into the proposal. The chat client renders a
checklist and posts the chosen ids as `POST /api/chat/confirm {approve, selection}`.
`confirm` forwards them as `Command(resume={"approve", "selection"})`; the approval
node merges `selection` into the paused action's `linked_note_ids` before running
it, so the user's pick — not the model's guess — is what the specialist writes.
Links are inserted directed (one edge source→target); the `note_links` table is
read as bidirectional.

## State and memory

LangGraph `PostgresSaver` is the durable execution store and supports exact-node
resume, checkpoint history, and fault recovery. `chat_threads` remains the
application projection and ownership boundary, not a second execution state
machine. Durable user memory is the note corpus, reached through semantic
search. Serializable state carries user id, clock, timezone, locale, citations,
trace data, messages, and pending action; nodes reconstruct their runtime `Ctx`.

`POST /api/chat` returns `{thread_id, status, reply?, action?, citations}`.
Citations are `{note_id,title,path,date}` — the read tools (`search_notes`,
`get_note`, `neighbors`) populate title/path/date when they surface a note. The
model references notes inline with `[[note:ID]]` markers (prompted, not quoting
titles/bodies); the chat UI replaces each marker with a compact note card
(title, path, date) that opens the full preview sheet. Markers the model emits
for a note no tool cited are resolved client-side via `GET /api/notesheet/{id}`.
If the model omits markers, the cited notes still render as cards below the
reply, so references are never lost. Confirmation/select action summaries carry
the same `[[note:ID]]` markers (the deterministic `summarize_write` emits them
for the note being acted on), so the confirm card also shows a preview card for
its target note, resolved the same way. `summarize_write` is localized: it takes
the caller's `locale` and renders each action's summary from `locales.json`
(`action_*` keys, en/uk), so confirmations read in the user's language.

## Safety and extension

All reads and writes are owner-scoped. The concrete reminder time is resolved
before confirmation and stored in the action, so approval cannot reinterpret
“tomorrow” against a later clock. Tool failures are returned as tool-result
strings. Add capabilities through a read-tool entry or an explicit specialist
handoff, preserving the graph's confirmation boundary.

Config: `AGENT_MODEL` and `AGENT_MAX_STEPS`. Streaming, parallel tool calls,
dynamic routing, and user-level saved-facts memory remain future extensions.
