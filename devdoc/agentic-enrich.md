# Agentic enrichment (capture-time)

Status: **agent built; not yet wired to a client.** The tool-using enrichment
agent (with the one-shot enricher as fallback) is complete and reserved for the
**web app's** future capture path. The Telegram bot deliberately keeps its
previous behaviour — fast capture + on-demand 🧠 Enrich (one-shot) — so its
`/internal/notes*` endpoints do **not** call this agent.

## Goal

Classify a freshly captured note into structured metadata (type / title / vault
path / tags / priority) at capture time, using tools over the user's own vault so
the classification stays consistent — mirroring the `agents/chat` structure so
both agents share one shape (tools · loop · service, keyed on `user_id`).

## Where it lives (layering)

Client-agnostic domain code in **`agents/enrich/`**. It's invoked server-side by
the capture endpoints (`api/routers/notes.py`) — not by any client directly. It
may call `services/` and `stores/` (like `agents/chat`), never a client.

## Building blocks

### Loop (planning) — `agents/enrich/loop.py`
A bounded single-tool-call loop (`ENRICH_AGENT_MAX_STEPS`). The model may call
read tools to gather context, then calls the terminal `submit_metadata` tool to
emit its final decision, which ends the run. On the last allowed step the loop
forces `tool_choice=submit_metadata`, so a run always ends with structured output
rather than a stray text turn.

### Tools (tool use) — `agents/enrich/tools.py`
Read tools (all wrap existing stores/services):
- `list_paths` — existing vault paths with counts (`note_store.list_paths`).
- `list_tags` — existing tags with counts (`note_store.list_tags`).
- `find_similar` — notes most similar to this one and how they were classified
  (`semantic.embed` + `chunk_store.similar_notes`), for a consistent decision.

Terminal tool:
- `submit_metadata(type, title, path, tags, priority)` — validated + guardrailed
  by reusing the one-shot enricher's `enrichment._normalize` (enforces the known
  root folder, two-level path cap, allowed types/priorities, tag cap).

### Service — `agents/enrich/service.py`
`enrich(user_id, note_id, text)`: builds the system prompt (reusing
`enrichment._root_folders` for the path rules) + the note, runs the loop, and
**persists** via `note_store.set_metadata`. If the loop doesn't converge (or
errors), it falls back to the existing one-shot `services/enrichment.enrich`, so
there is always a result. Never raises — a note is never lost to enrichment.

## Intended wiring (web app)

When the web app gains a capture path, that endpoint should call
`agents.enrich.enrich(user_id, note_id, text)` right after `note_service.capture_note`,
guarded so enrichment failure never fails the save, and surface the returned
metadata to the Mini App. The bot's `/internal/notes*` endpoints are intentionally
left alone (fast capture + deferred one-shot Enrich button), so immediate
enrichment applies only to the web app. Enrichment is text-only (no media
captions).

## Config

- `ENRICH_AGENT_MODEL` (default = `ENRICH_LLM_MODEL`) — the loop's model.
- `ENRICH_AGENT_MAX_STEPS` (default `4`) — max tool-call iterations.

## Not in this pass

Merging the on-demand Enrich button onto the agent, enriching media captions, and
streaming progress. All fit behind the existing loop/tool/service seams.
