# Agentic chat (Web App chat tab)

Status: **in progress** — read tools + write-with-confirmation, single-tool-call
loop. Streaming and sub-agent handoffs are deferred (interfaces left open).

## Goal

Turn the chat tab from a single-shot RAG answer into an **agent** that can plan,
call tools over the user's own notes/reminders/links, and answer with citations —
extensible by *adding a tool or a sub-agent*, never by editing the loop.

## Where it lives (layering)

Client-agnostic domain code in **`agents/chat/`**. Clients reach it through the
API only:

- Web app → `POST /api/chat` and `POST /api/chat/confirm` (initData auth).
- Bot (future) → the same `/api/chat` endpoint over `agents/chat`.

Everything keys on the internal `user_id`; tools are per-user scoped and
permission-checked. No client touches the DB or the LLM directly.

## Building blocks (planning · tool use · state · memory · handoffs)

### Loop (planning) — `agents/chat/loop.py`
A bounded ReAct loop: the model proposes **one** tool call (we set
`parallel_tool_calls=False` so each step is a single call, which keeps the
confirmation protocol simple) → we execute it → feed the result back → repeat
until the model answers or `AGENT_MAX_STEPS` is hit. Watchdogs: max steps,
per-call timeout, and the model/token budget from config. The planner is a plain
tool-calling loop today ("agentic RAG"); it's isolated so it can be upgraded to
explicit plan-then-execute later without touching tools or transport.

### Tools (tool use) — `agents/chat/tools.py`
Each tool is `{name, description, JSON schema, handler(ctx, args)}` and **wraps an
existing service** (no duplicated logic). `ctx` carries `user_id`, `now`, `tz`,
`locale`. A single `TOOL_SPECS` (OpenAI function schemas) + `execute_tool()`
dispatch. Tools are split into read and write; `WRITE_TOOLS` names the ones that
require confirmation.

Initial read tools:
- `search_notes(query)` — agenda-aware RAG answer over the user's notes
  (`search_service.answer`); the retrieval workhorse.
- `get_note(note_id)` — one note's full detail (`note_store.get_note_for_user`).
- `neighbors(note_id)` — a note's directly linked notes (`link_store`).
- `list_reminders()` — upcoming reminders (`reminders.upcoming`).
- `list_paths()` — the user's folder vocabulary (`note_service.known_paths`).

Initial write tools (confirmation required):
- `create_reminder(text)` — capture a note + schedule its reminder.
- `set_note_path(note_id, path)` — move a note to a validated vault path.

Adding a capability = append one entry to the registry. Nothing else changes.

### State — `stores/chat_store.py` (+ migration `0019_chat_threads`)
A `chat_threads` row per conversation holds the running `messages` array (the
provider message list, including assistant tool-calls and tool results) and a
`pending` blob (a paused write awaiting confirmation). The client passes a
`thread_id` back on each turn to continue. Short-term state = the thread; the
turn's scratchpad = the tool call/result messages appended during the loop.

### Memory
Durable memory is the notes themselves — already embedded — reached via
`search_notes`/`get_note`. Short-term memory is the thread history. A future
user-level "saved facts" memory can be added as another tool + store without
changing the loop.

### Handoffs (future)
A registry of specialised sub-agents (e.g. a retrieval specialist vs an action
specialist). Today there is one generalist; the loop calls a single agent config
(system prompt + tool subset), and that seam is where a handoff/router will slot
in.

## Write-with-confirmation protocol

1. The model calls a write tool. The loop does **not** execute it; it persists the
   thread (including the assistant message carrying the `tool_call`) plus
   `pending = {tool_call_id, name, args, summary}` and returns
   `{status: "confirm", action: {name, args, summary}, thread_id}`.
2. The client shows a Confirm / Cancel prompt.
3. `POST /api/chat/confirm {thread_id, approve}` resumes: on approve we execute
   the write and append its result as the pending `tool_call`'s tool message; on
   decline we append a "user declined" tool message. Either way the loop continues
   from there and returns the final answer.

Only one write may be pending at a time (guaranteed by `parallel_tool_calls=False`).

## Transport & response shape

`POST /api/chat {message, thread_id?}` →
`{thread_id, status: "answer"|"confirm", reply?, action?, citations?}`.
`citations` are `[{note_id, title}]` the agent referenced, so the client renders
chips that open the existing note card. Streaming (SSE of tokens/steps) is a later
pass; the current UI already posts to this seam and degrades gracefully.

## Safety / watchdogs

Read-only by default; every write goes through the confirmation step above.
`AGENT_MAX_STEPS` bounds the loop; each tool call is wrapped so a failing tool
returns an error string to the model (never crashes the turn); all tool calls are
logged with `user_id` + args. Tools only ever see the caller's own data.

## Config

- `AGENT_MODEL` (default `gpt-4o-mini`) — the loop's model.
- `AGENT_MAX_STEPS` (default `6`) — max tool-call iterations per turn.

## Not in this pass (extension points)

Streaming responses, sub-agent handoffs/routing, user-level saved-facts memory,
parallel tool calls, and richer planners (plan-then-execute). All fit behind the
existing loop/tool/session seams.
