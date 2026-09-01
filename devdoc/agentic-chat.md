# Agentic chat (Web App chat tab)

Status: **Q&A + specialist write handoffs.** Chat answers with owner-scoped read
tools and delegates writes to Enrich or Reminder. Every write pauses for explicit
confirmation; Chat never mutates data directly.

## Workflow and tools

`agents/conversation/graph.py` defines the bounded LangGraph `CHAT_GRAPH`. The model emits
at most one tool call per step (`parallel_tool_calls=False`), and conditional
edges route it to:

- `read_tool` for `search_notes`, `get_note`, `neighbors`, `list_reminders`,
  `list_agenda`, or
  `list_paths`;
- `enrich_agent` for `perform_action(instruction)` — create a note, move a note,
  or enrich/classify it;
- `reminder_agent` for `set_reminder(instruction)` — resolve and schedule a
  reminder;
- END when the model answers without a tool.

Read results loop back to the model until it answers or `AGENT_MAX_STEPS` is
used. `search_notes` returns structured evidence rather than calling another
LLM; the Conversation model produces the grounded answer on the next graph step.
`final` provides a tool-free bounded fallback.

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

## State and memory

LangGraph `PostgresSaver` is the durable execution store and supports exact-node
resume, checkpoint history, and fault recovery. `chat_threads` remains the
application projection and ownership boundary, not a second execution state
machine. Durable user memory is the note corpus, reached through semantic
search. Serializable state carries user id, clock, timezone, locale, citations,
trace data, messages, and pending action; nodes reconstruct their runtime `Ctx`.

`POST /api/chat` returns `{thread_id, status, reply?, action?, citations}`.
Citations are `{note_id,title}` chips that open notes in the existing UI.

## Safety and extension

All reads and writes are owner-scoped. The concrete reminder time is resolved
before confirmation and stored in the action, so approval cannot reinterpret
“tomorrow” against a later clock. Tool failures are returned as tool-result
strings. Add capabilities through a read-tool entry or an explicit specialist
handoff, preserving the graph's confirmation boundary.

Config: `AGENT_MODEL` and `AGENT_MAX_STEPS`. Streaming, parallel tool calls,
dynamic routing, and user-level saved-facts memory remain future extensions.
