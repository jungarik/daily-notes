# Project context

**This is a production app, not a POC.** It's a personal knowledge / brain-dump
system the owner uses daily. Treat it accordingly: correctness, resilience, and
maintainability matter more than shipping fast.

## What it is

A backend for capturing thoughts (text/voice), enriching them into structured
notes (type/title/path/tags/priority), reminders, semantic search + RAG answers,
and human-curated links between notes (Zettelkasten-style). Notes are meant to be
exportable to an Obsidian-style vault.

## Architecture — multi-client backend

This is **not** just a Telegram bot. The Telegram bot is **one client adapter**.
Planned clients: Telegram bot, web app, iOS app. A separate **API service**
(`api/`, FastAPI) fronts the same domain layer and runs as its own Railway
service on the project's private network; clients call it over
`http://<service>.railway.internal:<port>`. It is currently an empty scaffold
(health + a token-guarded `/internal` namespace); the bot still calls the
services in-process, with `api_client.py` as the seam for switching later.

Consequences (follow these):

- **No business/domain logic in `bot.py`.** The bot is a thin Telegram adapter:
  translate updates → call the domain/service layer → format the reply. Capture,
  enrichment orchestration, reminder creation, link selection, search/answer must
  live in reusable service/domain modules that every client (and the future API)
  can call.
- Keep the layering one-way: clients → services (domain) → stores → db/config.
  Stores never import services; services never import a client.
- **Clients don't touch the database.** In the target architecture the API
  service is the *only* backend gateway for a client: the bot (and web/iOS) call
  the API, never `db`/stores directly. Because the domain keys on an internal
  `user_id`, a thin client first exchanges its external identity for a `user_id`
  (`POST /internal/users/resolve` with a Telegram `chat_id`), caches it, then
  passes `user_id` to every other endpoint. `chat_id` is the *only*
  Telegram-specific field the API knows about; everything else is client-agnostic.
  (Today the bot still calls services/stores in-process — transitional — with
  `api_client.py` as the seam.)
- `chat_id` and other Telegram specifics stay at the adapter edge; internally use
  `user_id` (already done).

## Production standards

- **Logging**: consistent, leveled, structured where useful. Log key domain
  events (capture, enrich, reminder fire, link) and all handled errors with
  context. No `print`.
- **Exception handling**: never swallow silently. Catch at boundaries, log with
  context, degrade gracefully (e.g. save the note even if enrichment fails), and
  surface a user-friendly message. Add a global error handler for each client
  (e.g. PTB `add_error_handler`).
- **Input validation / guardrails ("watchdogs")**: validate/normalise inputs at
  the edge; bound sizes (text length, attachment size, LLM token budgets);
  timeouts and retries on external calls (OpenAI, S3, Telegram); protect against
  runaway loops/costs.
- **Data safety**: migrations are append-only; take a snapshot before heavy ones.

## Layout (current)

Packages: **`services/`** (domain) and **`stores/`** (persistence); infra stays
at the repo root (`config`, `db`, `openai_client`, `storage`, `i18n`, `migrate`).

`bot.py` (thin Telegram adapter) → `services/` orchestration (`note_service`:
capture / enrich, `reminders`: detect + create, `search_service`: agenda-aware
RAG answer, `user_service`: identity + settings resolution, `links`: candidates
+ toggle) → `services/` domain helpers (`semantic`, `enrichment`,
`transcription`, `timeparser`) → `stores/` (`note_store`, `chunk_store`,
`reminder_store`, `link_store`, `user_store`) → `db`/`config`. Imports are
absolute: `from services import X`, `from stores import Y`. `bot.py` keeps only
Telegram specifics (keyboards, formatting, command wiring, reminder delivery,
global `add_error_handler`).

The `api/` service (FastAPI) reuses the same `services/`/`stores/`; it is the
backend gateway and **owns schema migrations** — it runs `migrate.run_migrations`
on startup (`api/main.py` lifespan). It deploys separately (`railway.api.json` →
`uvicorn api.main:app --host :: --port $PORT`) while the bot uses
`railway.bot.json` → `python bot.py`. See `api/README.md`.
