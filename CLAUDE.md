# Project context

**This is a production app, not a POC.** It's a personal knowledge / brain-dump
system the owner uses daily. Treat it accordingly: correctness, resilience, and
maintainability matter more than shipping fast.

## What it is

A backend for capturing thoughts (text / voice / photos), enriching them into
structured notes (type/title/path/tags/priority), reminders, semantic search +
RAG answers, and human-curated links between notes (Zettelkasten-style). Notes
are meant to be exportable to an Obsidian-style vault. A Telegram Mini App (web
app) is a first-class read/curate client on top of the same API.

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
  the edge; bound sizes (text length, attachment count/size, LLM token budgets);
  timeouts and retries on external calls (OpenAI, S3, Telegram); protect against
  runaway loops/costs. Env values are normalised too — e.g. `config._clean_url`
  strips a stray leading `$`/quotes/whitespace from `S3_ENDPOINT_URL` so a
  paste/interpolation slip can't silently break every upload.
- **Data safety**: migrations are append-only; take a snapshot before heavy ones.
  Deleting a note also purges its bucket objects (attachments + voice audio) via
  `storage.delete_object` — DB rows cascade, but object storage does not, so
  `note_service.delete_bare_note` collects the keys *before* deleting and removes
  them after a successful delete.

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
no `services`/`stores`/`db`. It captures text (`/internal/notes`), voice
(`/internal/notes/voice`), and photos (`/internal/notes/media`): a single photo
saves immediately; an album (several updates sharing a `media_group_id`) is
buffered with a short debounce and saved as one note with all images. The API
routers are thin: they validate at the edge (`api/schemas.py`) and compose
`services/` calls; only the API touches the database.

The `api/` service (FastAPI) reuses the same `services/`/`stores/`; it is the
backend gateway and **owns schema migrations** — it runs `migrate.run_migrations`
on startup (`api/main.py` lifespan). It deploys separately (`railway.api.json` →
`python -m api.run`, a dual-stack launcher — binds `::` with IPV6_V6ONLY=0 so
it serves both private IPv6 and the public IPv4 edge) while the bot uses
`railway.bot.json` → `python -m frontend.Telegram_Bot.bot`. See `api/README.md`.

## Web app (Telegram Mini App)

`frontend/Telegram_WebApp/index.html` is a single-file vanilla HTML/CSS/JS Mini
App served by the API itself at `/app` (via `NoCacheStaticFiles`, so it's
same-origin with the API — relative URLs like the image proxy just work). It is a
separate client from the bot and authenticates with Telegram's signed `initData`
(`X-Telegram-Init-Data` header, verified in `api/telegram_auth.py`) rather than
the `/internal` token; its endpoints live under `/webapp/*` in
`api/routers/webapp.py` and resolve the Telegram user to an internal `user_id`
before returning only that user's data: `GET /webapp/feed` (full note cards,
newest first), `GET /webapp/notes` + `/notes/{id}` (browser tree + preview),
`POST /webapp/notes/{id}/path` and `/webapp/folder/move` (rename a note's or a
whole folder's path — root folders can't be moved), `GET /webapp/graph`
(connections map), `GET /webapp/reminders/count` (active + future reminders, for
the header stat), and `GET /webapp/attachments/{id}?t=<token>` (the signed image
proxy). `POST /webapp/chat` + `/webapp/chat/confirm` back the **agentic chat tab**
(see below).

UI: a sticky **header** with Instagram-style stats (Notes / Links / Reminders)
and, on the Notes and Map tabs, a funnel **folder-filter** button. A floating
glass **dock** holds a center pill (Notes / Map / Browser icons, in that order)
flanked by two circle buttons — chat (left) and search (right). Tapping a circle
swaps the pill's icons for a shared input bar (with a Send button) and the pill
widens toward the borders; the active circle's glyph becomes a ✕ and doubles as
the close/back control (the opposite circle hides). Views: **Notes** (a feed of
note cards), **Browser** (folder tree), **Map** (canvas force-directed graph),
**Search** (client-side filter over loaded notes), **Chat** (conversation view
over the `/webapp/chat` seam). One card template (`buildPost`) is shared by the
feed and the bottom-sheet preview (opened from the browser/search/graph): image
carousel on top, then title (date at the end of the title line), path, tags, full
text, and a de-duplicated "Linked notes" list (depth-1 neighbours; tapping one
navigates without recursion). Path/localised-root names are written by the LLM
into the note path and stored localised (not translated at display time). The `⋮`
menu on a card/folder opens a context menu to change its path.

The **folder filter** is a tri-state checkbox tree (built client-side from the
loaded notes' paths): a parent is checked when all its descendants are, or
indeterminate when only some. The selection is persisted in `localStorage`
(survives tab switches and reopens) and applies to both the Notes feed and the
Map graph (nodes/edges outside the selected folders are dropped).

The **Map** uses a semantic-zoom + focus model. Nodes render as adaptive
rounded-rectangle cards that reveal more with zoom (title only when far → +
folder → + link count when near), the focused/selected node always expanded;
overlapping lower-priority cards are culled and a faint folder-coloured dot marks
every node. Tapping a node opens a **focused card** (title, path, link count,
tags/snippet fetched lazily) offering three branches: **Neighbors** (rebuild as a
depth-1 **ego graph** with a "Full graph" reset), **Open note** (the shared
preview sheet), and **Outline** (jump to the Browser tab, expand the note's
ancestor folders, scroll its row into view and flash it). Leaving the Map clears
the focus/ego state.

## Agentic chat

The chat tab is an **agent** (client-agnostic, in `services/agent/`) that plans,
calls tools over the user's own data, and answers with citations — see
`devdoc/agentic-chat.md`. A bounded single-tool-call ReAct loop (`agent/loop.py`,
`AGENT_MAX_STEPS`) drives a **tool registry** (`agent/tools.py`) where each tool
wraps an existing service: read tools (`search_notes` → `search_service.answer`,
`get_note`, `neighbors`, `list_reminders`, `list_paths`) and write tools
(`create_reminder`, `set_note_path`) that require confirmation. Conversation state
lives in `chat_threads` (`stores/chat_store.py`, migration `0019`) as the running
provider message list plus a `pending` paused write. A write pauses the loop and
returns `{status:"confirm", action}`; `POST /webapp/chat/confirm {approve}`
resumes — executing or declining the write, then continuing to the answer.
Extend by adding a tool (or, later, a sub-agent) — never by editing the loop.

## Design docs

`devdoc/` holds implementation specs for planned/agreed features (design agreed
but not yet built) as Markdown. Before implementing a feature, check `devdoc/`
for an existing spec and follow it; when a spec is fully implemented, update or
remove it. Current specs: `devdoc/plugin-capture-tokens.md` (personal access
tokens + public `/capture` for plugin clients — Chrome/Codex/Claude);
`devdoc/agentic-chat.md` (the agentic chat architecture — partly built: read
tools + write-with-confirmation shipped; streaming and sub-agent handoffs
deferred).
