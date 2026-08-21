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
`http://<service>.railway.internal:<port>`. The bot is **fully cut over**: it
calls the API for every domain operation (identity, capture, enrichment, links,
search, reminders + the dispatcher) through `api_client.py` and imports no
`services`/`stores` and no `db`. The API's `/internal` namespace exposes the
whole surface the bot needs.

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
  The bot caches the `chat_id → user_id` mapping to avoid a resolve round trip on
  every update.
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

`frontend/Telegram_Bot/bot.py` (thin Telegram adapter) →
`frontend/Telegram_Bot/api_client.py` → **`api/`** (FastAPI
gateway) → `services/` orchestration (`note_service`: capture / enrich,
`reminders`: detect + create + dispatch state, `search_service`: agenda-aware
RAG answer, `user_service`: identity + settings resolution, `links`: candidates
+ toggle) → `services/` domain helpers (`semantic`, `enrichment`,
`transcription`, `timeparser`) → `stores/` (`note_store`, `chunk_store`,
`reminder_store`, `link_store`, `user_store`, `attachment_store`) → `db`/`config`.
Media files (images; up to `ATTACHMENT_MAX_COUNT` per note) are captured via the
multipart `POST /internal/notes/media` endpoint, uploaded to the same S3 bucket
as voice audio (`storage.upload_attachment`, keyed under `attachments/`) and
recorded one-to-many in `note_attachments` (`kind` leaves room for video/pdf/doc
and folding voice audio in later). Enrichment/search still use text only; the
web app renders a note's attachments as a swipe carousel, loading each image
through the API proxy `GET /webapp/attachments/{id}?t=<token>` (a short-lived
HMAC token from `api/media_token.py` is the auth, since an `<img>` can't send the
initData header) which streams the bytes via `storage.fetch_object` — the API
reaches the bucket even when the browser can't (private endpoint), so this works
regardless of bucket public reachability. Imports are
absolute: `from services import X`, `from stores import Y`. `bot.py` keeps only
Telegram specifics (keyboards, formatting, command wiring, reminder *delivery*,
global `add_error_handler`) and calls the API for everything else — it imports
no `services`/`stores`/`db`. The API routers are thin: they validate at the edge
(`api/schemas.py`) and compose `services/` calls; only the API touches the
database.

The `api/` service (FastAPI) reuses the same `services/`/`stores/`; it is the
backend gateway and **owns schema migrations** — it runs `migrate.run_migrations`
on startup (`api/main.py` lifespan). It deploys separately (`railway.api.json` →
`python -m api.run`, a dual-stack launcher — binds `::` with IPV6_V6ONLY=0 so
it serves both private IPv6 and the public IPv4 edge) while the bot uses
`railway.bot.json` → `python -m frontend.Telegram_Bot.bot`. See `api/README.md`.

## Design docs

`devdoc/` holds implementation specs for planned/agreed features (design agreed
but not yet built) as Markdown. Before implementing a feature, check `devdoc/`
for an existing spec and follow it; when a spec is fully implemented, update or
remove it. Current specs: `devdoc/plugin-capture-tokens.md` (personal access
tokens + public `/capture` for plugin clients — Chrome/Codex/Claude).
