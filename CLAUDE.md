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
search, reminders + the dispatcher) through `api_client.py` (targeting the
`/api/telegram_bot/*` surface) and imports no domain code and no `db`. Every
user-scoped endpoint accepts either the browser's Telegram `initData` (identity
derived server-side) or the bot's internal token + `X-User-Id` header
(`api/deps.current_user`). Privileged, cross-user plumbing
(identity `resolve`, the reminder dispatcher) stays token-only
(`require_internal_token`).

Consequences (follow these):

- **No business/domain logic in `bot.py`.** The bot is a thin Telegram adapter:
  translate updates → call the API → format the reply. Capture, enrichment
  orchestration, reminder creation, link selection, search/answer live server-side
  in the `api/telegram_bot` section (which owns its own domain + persistence).
- Keep the layering one-way: every vertical → shared infra (`db`, `config`,
  `i18n`, `openai_client`, `file_store`, `api/deps`, `api/media_token`). There is
  no shared domain layer — each section/agent owns (duplicates) the domain +
  persistence it needs, so one vertical's logic can't ripple into another.
- **Clients don't touch the database.** In the target architecture the API
  service is the *only* backend gateway for a client: the bot (and web/iOS) call
  the API, never `db`/stores directly. Because the domain keys on an internal
  `user_id`, a thin client first exchanges its external identity for a `user_id`
  (`POST /api/users/resolve` with a Telegram `chat_id`), caches it, then sends it
  in the `X-User-Id` header on every other call. A browser never sends `user_id` —
  it's derived from `initData`, so a public caller can't impersonate another user.
  `chat_id` is the *only* Telegram-specific field the API knows about; everything
  else is client-agnostic. The bot caches the `chat_id → user_id` mapping to avoid
  a resolve round trip on every update.
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
  `file_store.delete_object` — DB rows cascade, but object storage does not, so
  `note_service.delete_bare_note` collects the keys *before* deleting and removes
  them after a successful delete.

## Layout (current)

The API is organised into **section verticals**, not shared service/store
layers. Each section is a self-contained folder under `api/` with the same three
files: **`endpoints.py`** (the FastAPI router), **`helper.py`** (its service /
shaping logic), and **`db.py`** (its own SQL). A section owns everything it
needs and is decoupled from the others — changing one section's logic can't
ripple into another (the trade-off is deliberately duplicated query/shaping code).

- **Web-app sections** (one per Mini App UI section): `feed`, `browser`,
  `notesheet`, `notecard`, `mapview`, `contextmenu`, `header`, `search`. These are
  fully isolated — they import only shared *infra* (`db`, `api.deps` for auth,
  `api.media_token`, `file_store`). Each serves its own URL prefix
  `/api/<section>` (e.g. `GET /api/feed`, `GET /api/notesheet/{id}`,
  `GET /api/mapview/graph`, `POST /api/contextmenu/notes/{id}/path`,
  `GET /api/header/stats`, `GET /api/search?q=`, and the image proxy
  `GET /api/notecard/attachments/{id}?t=<token>`).
- **`api/chat`** — the agentic chat tab (`POST /api/chat`, `/api/chat/confirm`).
  Thin: it resolves the caller's clock/locale (its own `db`) and delegates to
  the self-contained `agents.chat` reasoning engine.
- **`api/telegram_bot`** — the single folder for every bot interaction, all under
  `/api/telegram_bot` (capture text/voice/media, enrich, atomize, polish, delete,
  link-candidates/toggle, reminders + dispatcher, user resolve/settings, RAG
  `search`, `ping`). It owns its full domain in `helper.py` + `db.py`
  (embeddings, one-shot enrichment, reminder parsing, links, user settings, RAG).

There is **no shared domain layer** (the former `services/`/`stores/`/`common/`
are gone). Each vertical duplicates the domain + persistence it needs:
`api/telegram_bot` in its `helper.py`/`db.py`; `agents/chat` and `agents/enrich`
each in a self-contained `domain.py` (their `tools/loop/service` import it). Only
true infra is shared, at the repo root — `config`, `db`, `openai_client`, `i18n`,
`migrate`, and `file_store` (the S3 client) — plus `api/deps.py` (auth, incl. the
identity resolve) and `api/media_token.py`. `capture/Telegram_Bot` (the bot) and
`browser/webapp` (the Mini App) are the client adapters.

Media files (images; up to `ATTACHMENT_MAX_COUNT` per note) are captured via the
multipart `POST /api/telegram_bot/notes/media` endpoint, uploaded to the same S3
bucket as voice audio (`file_store.upload_attachment`, keyed under `attachments/`)
and recorded one-to-many in `note_attachments`. The web app renders a note's
attachments as a swipe carousel, loading each image through the notecard proxy
`GET /api/notecard/attachments/{id}?t=<token>` (a short-lived HMAC token from
`api/media_token.py` is the auth, since an `<img>` can't send the initData
header); the proxy streams bytes via `file_store.fetch_object` — the API reaches
the bucket even when the browser can't (private endpoint).

`bot.py` keeps only Telegram specifics (keyboards, formatting, command wiring,
reminder *delivery*, global `add_error_handler`) and calls the API for everything
else via `api_client.py` — it imports no domain code and no `db`. It captures text
(`/api/telegram_bot/notes`), voice (`…/notes/voice`), and photos (`…/notes/media`):
a single photo saves immediately; an album (updates sharing a `media_group_id`)
is buffered with a short debounce and saved as one note. Bot capture stays
**deferred** — the note saves fast and the user enriches on demand with the 🧠
Enrich button (one-shot enrichment in `api/telegram_bot/helper.py`). The
capture-time enrichment agent (`agents/enrich`) is reserved for the **web app** and
is not wired into the bot's capture endpoints.

The `api/` service (FastAPI) hosts the section verticals; it is the
backend gateway and **owns schema migrations** — it runs `migrate.run_migrations`
on startup (`api/main.py` lifespan). It deploys separately and its start command
is `python -m api.run` (the image's `CMD`), a dual-stack launcher — binds `::`
with IPV6_V6ONLY=0 so it serves both private IPv6 and the public IPv4 edge. The
API image is built from **`Dockerfile.api`** (single-stage Python — the API is a
pure `/api` gateway and serves no frontend). The Mini App is a **separate static
Railway service** built from **`Dockerfile.webapp`** (Vite build → a Caddy static
server, `browser/webapp/Caddyfile`, SPA fallback to `index.html`); it calls the
API cross-origin (hence CORS + `WEBAPP_ALLOWED_ORIGINS` on the API). The bot is
built from **`Dockerfile.bot`** (single-stage Python; `CMD python -m
capture.Telegram_Bot.bot`). Each of the three services selects its Dockerfile
via a `RAILWAY_DOCKERFILE_PATH` service variable (`Dockerfile.api` /
`Dockerfile.webapp` / `Dockerfile.bot`) set in the Railway dashboard — there are
no `railway.*.json` config-as-code files (Railway deprecated Config-as-Code; use
the dashboard or `.railway/railway.ts` IaC). See `api/README.md`.

## Web app (Telegram Mini App)

`browser/webapp/` is a **React + Vite** Mini App, deployed as its own static
host (Caddy) that calls the API cross-origin. It sets `VITE_API_BASE` (the API's
public origin, baked into the build) and builds with `base: "/"`. It is split by
section — one component per UI section (`Header`, `Dock`, `Feed`, `Browser`,
`MapView`, `Search`, `Chat`, `NoteSheet`, `ContextMenu`, `FolderFilter`) over a
small `AppContext` store (`store/AppContext.jsx`), with `lib/` for API access
(`api.js`), Telegram init (`telegram.js`) and formatting (`format.js`), and
`graph/engine.js` holding the imperative canvas graph engine used by `MapView`.
The shared note card lives in `components/NoteCard.jsx` (feed + preview sheet).
(The former vanilla single-file app has been removed.)
It is a
separate client from the bot and authenticates with Telegram's signed `initData`
(`X-Telegram-Init-Data` header, verified in `api/telegram_auth.py` via
`current_user`); it calls its per-section endpoints, which resolve the Telegram
user to an internal `user_id` and return only that user's data:
`GET /api/feed` (full note cards, newest first), `GET /api/browser` (tree) +
`GET /api/notesheet/{id}` (preview), `POST /api/contextmenu/notes/{id}/path` and
`/api/contextmenu/folder/move` (rename a note's or a whole folder's path — root
folders can't be moved), `GET /api/mapview/graph` (connections map),
`GET /api/header/stats` (Notes/Links/Reminders counts), `GET /api/search?q=`
(server-side search), and `GET /api/notecard/attachments/{id}?t=<token>` (the
signed image proxy). `POST /api/chat` + `/api/chat/confirm` back the **agentic
chat tab** (see below).

UI: a sticky **header** with Instagram-style stats (Notes / Links / Reminders)
and, on the Notes and Map tabs, a funnel **folder-filter** button. A floating
glass **dock** holds a center pill (Notes / Map / Browser icons, in that order)
flanked by two circle buttons — chat (left) and search (right). Tapping a circle
swaps the pill's icons for a shared input bar (with a Send button) and the pill
widens toward the borders; the active circle's glyph becomes a ✕ and doubles as
the close/back control (the opposite circle hides). Views: **Notes** (a feed of
note cards), **Browser** (folder tree), **Map** (canvas force-directed graph),
**Search** (client-side filter over loaded notes), **Chat** (conversation view
over the `/api/chat` seam). One card template (`buildPost`) is shared by the
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

The chat tab is an **agent** (client-agnostic, in `agents/chat/`) that plans,
calls tools over the user's own data, and answers with citations — see
`devdoc/agentic-chat.md`. A bounded single-tool-call ReAct loop (`agents/chat/loop.py`,
`AGENT_MAX_STEPS`) drives a **tool registry** (`agents/chat/tools.py`) where each tool
wraps `agents/chat/domain.py` (the agent's self-contained data access): read tools
(`search_notes`, `get_note`, `neighbors`, `list_reminders`, `list_paths`) and write
tools (`create_reminder`, `set_note_path`) that require confirmation. Conversation
state lives in `chat_threads` (`agents/chat/domain.py`, migration `0019`) as the running provider
message list plus a `pending` paused write. A write pauses the loop and returns
`{status:"confirm", action}`; `POST /api/chat/confirm {approve}` resumes —
executing or declining the write, then continuing to the answer.

**Citations.** Answers are grounded in the notes they drew on: `search_notes`
calls `domain.answer_with_sources` — which retrieves once and returns the answer
text *plus* the source note ids (retrieval and answer are split so it isn't run
twice) — and the tool cites
the distinct source notes (with a title, or a text snippet for un-enriched notes)
via `Ctx.cite`. `get_note` cites the note it opened. The API returns these as
`citations:[{note_id,title}]`; the chat UI renders them as chips that open the
note card. Extend by adding a tool (or, later, a sub-agent) — never by editing
the loop.

## Design docs

`devdoc/` holds implementation specs for planned/agreed features (design agreed
but not yet built) as Markdown. Before implementing a feature, check `devdoc/`
for an existing spec and follow it; when a spec is fully implemented, update or
remove it. Current specs: `devdoc/plugin-capture-tokens.md` (personal access
tokens + public `/capture` for plugin clients — Chrome/Codex/Claude);
`devdoc/agentic-chat.md` (the agentic chat architecture — partly built: read
tools + write-with-confirmation shipped; streaming and sub-agent handoffs
deferred); `devdoc/agentic-enrich.md` (the capture-time enrichment agent —
shipped, with the one-shot enricher as fallback).
