# Agentic chat (Web App chat tab)

Status: **Q&A + write-handoff** — the chat tab answers with read tools and, when
the user asks it to DO something, hands the action to the **enrich agent** via a
single `perform_action` tool; the write pauses for the user's confirmation. All
write *logic* lives in `agents/enrich/` (see `devdoc/agentic-enrich.md`); the chat
agent never mutates data directly. Streaming is deferred.

## Goal

Turn the chat tab from a single-shot RAG answer into an **agent** that can plan,
call tools over the user's own notes/reminders/links, and answer with citations —
extensible by *adding a tool or a sub-agent*, never by editing the loop.

## Where it lives (layering)

Client-agnostic domain code in **`agents/chat/`**. Clients reach it through the
API only:

- Web app → `POST /api/chat` and `POST /api/chat/confirm` (initData auth) — the
  confirm endpoint resumes a handed-off action.
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
Each tool is `{name, description, JSON schema, handler(ctx, args)}` wrapping this
package's `domain` (RAG) or `db` (reads). `ctx` carries `user_id`, `now`, `tz`,
`locale`. A single `TOOL_SPECS` (OpenAI function schemas) + `execute_tool()`
dispatch. Read tools run inline; the one handoff tool is intercepted by the loop.

Read tools:
- `search_notes(query)` — agenda-aware RAG answer over the user's notes
  (`domain.answer_with_sources`); the retrieval workhorse.
- `get_note(note_id)` — one note's full detail (`db.get_note_for_user`).
- `neighbors(note_id)` — a note's directly linked notes (`db.links_of_for_user`).
- `list_reminders()` — upcoming reminders (`db.upcoming_reminders`).
- `list_paths()` — the user's folder vocabulary (`domain.known_paths`).

Handoff tool (`HANDOFF_TOOLS`):
- `perform_action(instruction)` — the model calls this when the user wants to DO
  something. The loop routes the instruction to `enrich.plan_action`, which
  returns the concrete write, and pauses for confirmation (see Writes). The chat
  agent itself performs no writes. Adding a read capability = append one registry
  entry; adding a write = add it to the enrich agent's tools.

### State — `agents/chat/db.py` (+ migration `0019_chat_threads`)
A `chat_threads` row per conversation holds the running `messages` array (the
provider message list, including assistant tool-calls and tool results). The
client passes a `thread_id` back on each turn to continue. Short-term state = the
thread; the turn's scratchpad = the tool call/result messages appended during the
loop. (The `pending` column is unused here now — the enrich agent uses it for its
write-confirmation flow.)

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

## Writes — handoff to the enrich agent

The chat agent never mutates data. When the model calls `perform_action`:

1. The loop calls `enrich.plan_action(user_id, instruction, …)` — one LLM call over
   the enrich agent's write-tool schemas — which returns the concrete write
   `{name, args, summary}` (e.g. `create_reminder`), or `None` if it can't decide.
2. The loop persists the thread (incl. the assistant `perform_action` tool_call)
   plus `pending = {tool_call_id, action}` and returns
   `{status:"confirm", action:{name, args, summary}, thread_id}`.
3. The client shows Confirm / Cancel. `POST /api/chat/confirm {thread_id, approve}`
   resumes: on approve the loop runs `enrich.execute_action(...)` (which calls the
   enrich tool handler) and appends its result as the pending tool_call's message;
   on decline it appends a "declined" message. Either way the loop continues to a
   final reply.

So the enrich agent owns the write *logic* (create note/reminder, move, enrich);
the chat agent owns the conversation + confirmation UX. Only one action may be
pending at a time (`parallel_tool_calls=False`).

## Transport & response shape

`POST /api/chat {message, thread_id?}` →
`{thread_id, status: "answer"|"confirm", reply?, action?, citations}`. `citations`
are `[{note_id, title}]` the agent referenced, so the client renders chips that
open the existing note card; `action` is the enrich agent's proposed write.
Streaming (SSE of tokens/steps) is a later pass; the current UI already posts to
this seam and degrades gracefully.

## Safety / watchdogs

The chat agent runs no writes directly; every write is a handed-off action the
user confirms before the enrich agent executes it.
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
