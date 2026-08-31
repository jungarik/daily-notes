# Agentic enrichment / actions

Status: **action agent built; not yet wired to a client.** The enrich agent is
the **write/action agent** for the user's notes: it creates notes, creates
reminders (from time-bearing instructions), moves notes to a vault path, and
classifies/enriches note metadata — each with a Confirm/Cancel step. Reserved for
the **web app's** future capture/action path; the Telegram bot keeps its own
behaviour (fast capture + on-demand 🧠 Enrich) and does **not** call this agent.
The chat agent is now read-only (Q&A); all writes moved here.

## Goal

Take natural-language instructions and act on the user's own vault — create a
note, create a reminder, move a note, or classify/enrich one — with a
confirmation step before each write, using tools over the user's own vault so the
result stays consistent. Mirrors the `agents/chat` shape (tools · loop · service,
keyed on `user_id`).

## Where it lives (layering)

Client-agnostic code in **`agents/enrich/`**, reserved for the (future) web-app
capture path — not wired into the bot, which uses one-shot enrichment. It is
fully self-contained: its data access lives in `agents/enrich/domain.py`
(embeddings, note/chunk SQL, root-folder vocabulary, the one-shot enricher), and
it imports only shared infra (`db`, `config`, `i18n`, `openai_client`), never a
client and no shared domain layer.

## Building blocks

### Loop (planning) — `agents/enrich/loop.py`
A bounded single-tool-call ReAct loop (`ENRICH_AGENT_MAX_STEPS`) with
write-confirmation — the same pattern the chat agent originally used. The model
may call read tools freely; when it calls a **write** tool the loop pauses
(returns `{status:"confirm", action, pending}`) instead of executing, and
`resume_write` continues after the user approves/declines.

### Tools (tool use) — `agents/enrich/tools.py`
Read tools (context, wrap `db`):
- `list_paths` — existing vault paths with counts.
- `list_tags` — existing tags with counts.

Write tools (in `WRITE_TOOLS`, confirmation required; wrap `domain`):
- `create_note(text)` — persist a new note (chunk + embed) → `domain.capture_note`.
- `create_reminder(text)` — create a note AND its reminder from a time-bearing
  instruction → `domain.create_note_with_reminder` (gated LLM time parse).
- `set_note_path(note_id, path)` — move a note to a validated vault path
  → `domain.move_note`.
- `enrich_note(note_id)` — classify + persist metadata (type/title/path/tags/
  priority) via the one-shot enricher → `domain.enrich_note`.

### Service — `agents/enrich/service.py`
Turn-based (for a future direct enrich surface): `start_turn(user_id, message,
thread_id, now, tz, locale)` runs one instruction; `confirm(user_id, thread_id,
approve, …)` resumes a paused write. Thread state (running messages + `pending`
write) is persisted in the shared `chat_threads` table via `db`. Returns
`{thread_id, status:"answer"|"confirm", reply|action}`.

Stateless **handoff API** (used by the chat agent's `perform_action` tool):
- `plan_action(user_id, instruction, now, tz, locale)` — one LLM call over the
  write-tool schemas → `{name, args, summary}` for the single write the
  instruction implies, or `None`. Executes nothing.
- `execute_action(user_id, action, now, tz, locale)` — run a planned write's tool
  handler (after the user approved it). The chat agent owns the thread/confirm
  UX; this just exposes the write capability.

## Intended wiring (web app)

When the web app gains a capture/action surface, it calls
`agents.enrich.start_turn(...)` / `confirm(...)` behind an `/api` section (like the
chat tab), rendering the confirm card for pending writes. The bot's
`/api/telegram_bot/*` endpoints are left alone (fast capture + deferred one-shot
Enrich button). Note creation here is text-only (no media captions).

## Config

- `ENRICH_AGENT_MODEL` (default = `ENRICH_LLM_MODEL`) — the loop's model.
- `ENRICH_AGENT_MAX_STEPS` (default `4`) — max tool-call iterations.

## Not in this pass

Merging the on-demand Enrich button onto the agent, enriching media captions, and
streaming progress. All fit behind the existing loop/tool/service seams.
