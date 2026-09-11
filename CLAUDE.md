# Project context

**This is a production app, not a POC.** It's a personal knowledge / brain-dump
system the owner uses daily. Treat it accordingly: correctness, resilience, and
maintainability matter more than shipping fast.

**The agentic system is the core of this product, and it is built on an
extremely clean, extendable, maintainable, scalable and readable architecture.**
Agent behaviour will keep growing — new tools, new steps, new specialists — so
the structure must stay obvious enough to extend without re-reading the whole
graph. When a change makes an agent harder to read or extend, it is the wrong
change, even if it works. See **Agentic architecture standards** below.

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

## Agentic architecture standards

These are binding for `agents/` and `tools/`. They exist so a new capability is
additive — a file plus an edge or a map entry — and never a rewrite of the loop.

- **One node, one module, one public `run`.** Every graph node is its own module
  exposing exactly `run(state) -> dict`. Everything else in the module is private
  (`_`-prefixed). No module hosts two nodes.
- **Name nodes for their role, not their implementation.** The loop primitives
  are `reason` (model step), `act` (run a tool), `plan` (one-shot planning),
  `approve` (human confirmation + execution), `handoff` (route to a specialist).
  Multi-step phases live in subpackages named for their goal — `classify/`,
  `schedule/`, `write/`. Graph node ids, module names, and trace labels match.
- **Nodes are pure state transitions.** `run` takes state and returns a partial
  state patch — never a mutation of the state it was handed. No cross-node
  imports, no shared mutable module state. The node's `run` is the one place that
  may be impure (retrieval, LLM, tool execution); everything it calls below that
  takes data as parameters and returns data. A local `_shared.py` is allowed only
  for genuinely pure helpers — mapping and retrieval stay in the node.
- **Routing is declarative and lives in `routing.py`.** Small predicate functions
  returning a node id; the graph shape is documented in the module docstring. No
  business logic in edges.
- **Extend by data, not by branching.** Prefer a registry/map over a new `if`:
  a new specialist is a `HANDOFF_SPECIALIST` entry plus a tool spec; a new tool
  is a file in `tools/<agent>/` registered in that package. Never edit the loop
  to add a capability.
- **Deterministic work belongs in its own node, not inside a write node.**
  Retrieval, classification, and time resolution are separate, testable steps
  (`classify_gather`, `schedule_resolve`, `link_context`); the write nodes stay
  plain checks.
- **No redundant nodes.** If a node is another node in a different mode, fold it
  in (as the tool-free budget exhaustion path folded into `reason`).
- **Keep the graph small enough to hold in your head.** Prefer the fewest nodes
  that express the flow; a reader should be able to follow `START → END` from
  `graph.py` + `routing.py` alone.
- **Docs and tests track the structure.** When node names or the graph change,
  update `devdoc/agent-workflows-langgraph.md`, the relevant `devdoc/agentic-*.md`,
  and the node-set assertions in `tests/`.

## Project code style

- Keep standalone `if` blocks separated from surrounding logic with a single
  empty line.
- If a method has a multi-line body, leave one empty line before its final
  `return` statement. Do not add that empty line for a single-return method.
- **Resolve to one value, then branch once.** When several conditions lead to
  the same outcome, don't give each its own branch — collapse them first. Guard
  the lookup with a ternary so a missing input and a missing row both arrive as
  `None`, then write a single `if/else` over that one value. The result is two
  lines of control flow for what is genuinely two outcomes, with both calls
  visible in the caller and no helper to look up:

  ```python
  # wrong — nested branches, and the tail return quietly serves two cases
  def _get_or_create_thread(user_id, thread_id):
      if thread_id is not None:
          thread = db.get_thread(user_id, thread_id)

          if thread is not None:
              return thread["id"], list(thread["messages"]), thread.get("pending")

      return db.create_thread(user_id), [], None

  # also wrong — flat, but it invents a helper and repeats the create call
  # once per way of not having a thread
  def _get_or_create_thread(user_id, thread_id):
      if thread_id is None:
          return db.create_thread(user_id), [], None

      thread = db.get_thread(user_id, thread_id)

      if thread is None:
          return db.create_thread(user_id), [], None

      return thread["id"], list(thread["messages"]), thread.get("pending")

  # right — normalise to `thread`, then one branch on "have it / don't"
  thread = db.get_thread(user_id, thread_id) if thread_id is not None else None

  if thread is None:
      thread_id, messages, pending = db.create_thread(user_id), [], None
  else:
      thread_id, messages, pending = (
          thread["id"],
          list(thread["messages"]),
          thread.get("pending"),
      )
  ```

  A ternary is the right tool for that guarded lookup: it says "read only if
  there is something to read" in one line, and the read still happens in the
  top-level caller where the rest of the I/O lives. Reach for early-return
  guards instead when the cases have genuinely *different* outcomes — an
  unreachable state, a validation failure, a short-circuit reply; don't nest the
  real work inside an `if` to reach them.
- If a function or method call passes more than 3–4 arguments, put each argument
  on its own line.
- For Python multi-line call/object/dict/list blocks, keep the opening bracket
  on the caller/assignment/expression line, put each field or argument on its
  own line, and put the closing bracket on its own line. For example, use
  `helper.json_text({` and `result.append({`, not a standalone `{` on the next
  line.
- **One responsibility per method.** Don't fold "build the input" and "perform
  the side effect" into the same method. A method that assembles a payload (e.g.
  a request/args/config dict) should just build and return it; the caller makes
  the external call. For example, prefer a `_build_request(...) -> dict` helper
  that returns the request, and let the caller invoke
  `model_gateway.chat_completion(**_build_request(...))`, rather than a single
  `_complete()` that both builds the request and calls the API. This keeps the
  payload construction independently testable and reusable, and keeps the
  side-effecting call visible at the call site.
- **Functions are pure by default.** A function takes data as parameters and
  returns new data. It does not perform I/O (DB, network, filesystem, LLM), does
  not read or write mutable module/global state, and does not depend on anything
  it wasn't given. Impurity is allowed only where it is the point — the top-level
  caller (a node's `run`, an endpoint handler, a tool's `invoke`).
- **Retrieve and map at the top-level caller.** The caller fetches the rows,
  resolves the context, and maps them into plain values, then passes those values
  down as parameters. A lower-level function never reaches out for what it needs;
  if it needs a note, the note is a parameter — not a `note_id` it will look up.
- **Never pass a handle so the callee can fetch.** If a function's job is to
  select, extract, or shape, give it the *data* — never the thing that can
  produce the data (`graph`, `db`, a client, a session, a checkpointer, a
  registry). Passing a handle plus its config buries I/O inside what reads like a
  mapper, and hides from the call site what was actually read:

  ```python
  # wrong — takes the graph + config only to fetch inside, and hands the
  # snapshot straight back out again
  def _latest_or_projection(graph, graph_config, messages, pending):
      snapshot = graph.get_state(graph_config)
      ...

  # right — the caller performs the read, the helper only chooses
  state_snapshot = graph.get_state(graph_config)
  messages, pending = _latest_or_projection(state_snapshot, messages, pending)
  ```
- **Don't return a parameter back to the caller.** A helper returns only what it
  derived. Handing an input back out in a tuple (the snapshot the caller just
  fetched) blurs who owns the value and makes the signature lie about the work.
- **Take the field, never the container it came from.** If the body only reads
  one attribute off a parameter, that attribute *is* the parameter. Reaching
  through an argument (`state_snapshot.tasks`, `note.id`, `response.choices`)
  couples the helper to a type it has no business knowing and hides what it
  actually operates on. The caller owns the object and does the attribute access:

  ```python
  # wrong — takes a whole snapshot to look at one collection, and the name
  # describes the snapshot rather than the check
  def is_interrupted(snapshot) -> bool:
      return any(task.interrupts for task in snapshot.tasks)

  # right — it checks tasks, so it takes tasks, and says so
  def has_interrupts(tasks) -> bool:
      return any(task.interrupts for task in tasks)

  checkpoint.has_interrupts(state_snapshot.tasks)
  ```

  Corollary: **name the function after the question it answers about its own
  parameter** — `has_interrupts(tasks)`, not `is_interrupted(snapshot)`.
- **Never accept a parameter the body doesn't use.**
- **Don't wrap a single call in a helper.** A private function whose whole body
  is one call adds a name to read past and hides the real operation — especially
  when the name is vague. Call it directly at the call site:

  ```python
  # wrong — "project" hides that this saves the thread, and saves nothing else
  def _project(thread_id, result):
      db.save_thread(thread_id, result.get("messages") or [], result.get("pending"))

  # right — the call site says what happens
  db.save_thread(thread_id, result.get("messages") or [], result.get("pending"))
  ```

  Extract a helper only when it removes real duplication of *logic* (branching,
  shaping, validation), not to alias a call or to save a few characters.
- **Name a value for what it is, not its shape.** `state_snapshot` not
  `snapshot`; `tool_call` not `call`; `model_request`/`model_response` not
  `request`/`response`. Avoid bare generic nouns (`data`, `result`, `info`,
  `item`, `obj`, `value`) wherever a domain-qualified name exists.
- **Never mutate by reference.** Do not modify a passed dict/list/object in place
  and never use that mutation as an output channel. Build and return a new value
  (`{**data, "field": x}`, a new list); the caller uses the returned result. The
  only thing a function communicates back is its return value.
- **No shared/common module unless it is 100% pure.** A helper may be shared only
  if it is completely side-effect-free and self-contained. Anything that fetches,
  resolves context, or carries state stays local to the vertical that uses it.
  **A mapper does not count as pure for this rule** — mapping belongs to its
  caller, not to a shared module.
- **Prefer duplication over an impure shared helper.** Copying a mapping/shaping
  function into two verticals is the correct trade here; it keeps verticals
  decoupled (same reasoning as "no shared domain layer" above). Do not create a
  `common`/`shared` home for convenience.
- Prefer these rules for new and changed code in this project; do not reformat
  unrelated code just for style.

## Layout (current)

The API is organised into **section verticals**, not shared service/store
layers. Each section is a self-contained folder under `api/` with the same three
files: **`endpoints.py`** (the FastAPI router), **`helper.py`** (its service /
shaping logic), and **`db.py`** (its own SQL). A section owns everything it
needs and is decoupled from the others — changing one section's logic can't
ripple into another (the trade-off is deliberately duplicated query/shaping code).

- **Web-app sections** (one per Mini App UI section): `feed`, `explorer`,
  `notesheet`, `notecard`, `mapview`, `contextmenu`, `header`, `search`. These are
  fully isolated — they import only shared *infra* (`db`, `api.deps` for auth,
  `api.media_token`, `file_store`). Each serves its own URL prefix
  `/api/<section>` (e.g. `GET /api/feed`, `GET /api/notesheet/{id}`,
  `GET /api/mapview/graph`, `POST /api/contextmenu/notes/{id}/path`,
  `GET /api/header/stats`, `GET /api/search?q=`, and the image proxy
  `GET /api/notecard/attachments/{id}?t=<token>`).
- **`api/chat`** — the agentic chat tab (`POST /api/chat`, `/api/chat/confirm`).
  Thin: it resolves the caller's clock/locale (its own `db`) and delegates to
  the self-contained `agents.conversation` controller.
- **`api/telegram_bot`** — the single folder for every bot interaction, all under
  `/api/telegram_bot` (capture text/voice/media, enrich, atomize, polish, delete,
  link-candidates/toggle, reminders + dispatcher, user resolve/settings, RAG
  `search`, `ping`). It owns its full domain in `helper.py` + `db.py`
  (embeddings, one-shot enrichment, reminder parsing, links, user settings, RAG).

There is **no shared domain layer** (the former `services/`/`stores/`/`common/`
are gone). Each vertical duplicates the domain + persistence it needs:
`api/telegram_bot` in its `helper.py`/`db.py`; `agents/conversation` owns reads
and orchestration, while `agents/enrich` owns confirmed writes. Only
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
section — one component per UI section (`Header`, `Dock`, `Feed`, `Explorer`,
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
`GET /api/feed` (full note cards, newest first), `GET /api/explorer` (tree) +
`GET /api/notesheet/{id}` (preview), `POST /api/contextmenu/notes/{id}/path` and
`/api/contextmenu/folder/move` (rename a note's or a whole folder's path — root
folders can't be moved), `GET /api/mapview/graph` (connections map),
`GET /api/header/stats` (Notes/Links/Reminders counts), `GET /api/search?q=`
(server-side search), and `GET /api/notecard/attachments/{id}?t=<token>` (the
signed image proxy). `POST /api/chat` + `/api/chat/confirm` back the **agentic
chat tab** (see below).

UI: a sticky **header** with Instagram-style stats (Notes / Links / Reminders)
and, on the Notes and Map tabs, a funnel **folder-filter** button. A floating
glass **dock** holds a center pill (Notes / Map / Explorer icons, in that order)
flanked by two circle buttons — chat (left) and search (right). Tapping a circle
swaps the pill's icons for a shared input bar (with a Send button) and the pill
widens toward the borders; the active circle's glyph becomes a ✕ and doubles as
the close/back control (the opposite circle hides). Views: **Notes** (a feed of
note cards), **Explorer** (folder tree), **Map** (canvas force-directed graph),
**Search** (client-side filter over loaded notes), **Chat** (conversation view
over the `/api/chat` seam). One card template (`buildPost`) is shared by the
feed and the bottom-sheet preview (opened from the explorer/search/graph): image
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
preview sheet), and **Outline** (jump to the Explorer tab, expand the note's
ancestor folders, scroll its row into view and flash it). Leaving the Map clears
the focus/ego state.

## Agentic chat

The chat tab is a **Q&A agent that hands off writes** (client-agnostic, in
`agents/conversation/`) — see `devdoc/agentic-chat.md`. A bounded LangGraph
single-tool-call ReAct workflow (`agents/conversation/graph.py`, `AGENT_MAX_STEPS`) drives
read tools from `tools/conversation/`: schemas, tool handlers, and tool DB calls
live outside the agent folder (`search_notes`, `get_note`, `neighbors`,
`list_reminders`, `list_agenda`, `list_paths`, `detect_reminder` — a deterministic
reminder classifier the model can call cheaply). The graph is four role-named
nodes — `reason`, `act`, `handoff`, `approve` — each a module under
`conversation/nodes/` with a single public `run`; `handoff` routes to the owning
specialist via the `HANDOFF_SPECIALIST` map, and `reason` makes a tool-free call
once the step budget is spent (no separate `final`/`pre_route` nodes). Conversation owns the explicit specialist handoffs:
`perform_action(instruction)` for note actions and `set_reminder(instruction)` for
scheduling. The chat agent
**never mutates data itself**: the loop routes every write to the **enrich agent**
(`agents/enrich/`), whose reminder capability also plans reminder actions. Enrich
proposes the concrete write, and the loop pauses
(`{status:"confirm", action}`), and `POST /api/chat/confirm {approve}` resumes,
running it through the same specialist. `api/telegram_bot` retains its independent reminder detection,
creation, and delivery implementation. Conversation state lives in `chat_threads`
(`agents/conversation/db.py`, migration `0019`) as the application projection plus a
`pending` handed-off action. `POST /api/chat` returns `{status:"answer", reply,
citations}` or `{status:"confirm", action}`.

**Agent tools.** Concrete tool implementations live in the root-level `tools/`
package, not inside `agents/*/tools`. Use `tools/conversation/` for chat read
tools and `tools/enrich/` for note write/enrichment/reminder tools. Each tool
file exposes `invoke(context: dict, args: dict)` and returns `ToolResult` with
typed `data: dict`. Tool specs stay with their tool namespace as
`tools/conversation/specs.py` and `tools/enrich/specs.py`. Agents import tool
registries/specs from these packages and execute them through
`agents/runtime/execute_tool.py`; callers render `ToolResult.data` to JSON text
only at graph/API boundaries.

**Citations.** Answers are grounded in the notes they drew on: `search_notes`
retrieves structured note evidence and returns a `ToolResult` with `data`,
`citations`, and `retrieved_chunks`. Tools do not call `Ctx.cite` or mutate
conversation trace directly. `agents/conversation/state.py` owns context mapping
and merge helpers (`tool_context`, `apply_tool_result`), while the read node
renders `ToolResult.data` to JSON text for the model. The API returns citations
as `citations:[{note_id,title}]`; the chat UI renders them as chips that open
the note card. Extend by adding a tool file under `tools/` and registering it in
the corresponding tool package — never by editing the loop.

## Agent evaluation and observability

`api/evals/` provides internal-token-protected dry-run evaluation for Chat,
Enrich, and Reminder; see `devdoc/agent-evaluation-observability.md`. Runs and
results reference completed `chat_threads` turns (migration `0020`);
the final schema has no `eval_cases` table. Chat replay never approves writes;
Enrich/Reminder evaluate extracted handoff planning only. Structured traces
capture routes, tools, and retrieved chunks. The LLM
judge is controlled by `AGENT_EVAL_JUDGE_ENABLED`. Hidden Telegram commands
`/eval` and `/eval_metrics` resolve the caller normally from `chat_id` to
`users.id`; the API authorizes that internal id against chat ids configured in
`EVAL_ADMIN_TELEGRAM_IDS`. The bot contains no allowlist logic.

## Design docs

`devdoc/` holds implementation specs for planned/agreed features (design agreed
but not yet built) as Markdown. Before implementing a feature, check `devdoc/`
for an existing spec and follow it; when a spec is fully implemented, update or
remove it. Current specs: `devdoc/plugin-capture-tokens.md` (personal access
tokens + public `/capture` for plugin clients — Chrome/Codex/Claude);
`devdoc/agentic-chat.md` (the agentic chat architecture — partly built: read
tools + specialist write handoffs shipped; streaming deferred);
`devdoc/agentic-enrich.md` (the note action/enrichment agent);
`devdoc/agentic-reminder.md` (the reminder capability);
`devdoc/agent-workflows-langgraph.md` (the implemented State / Nodes / Edges);
and `devdoc/agent-evaluation-observability.md` (evaluation runs and metrics).
