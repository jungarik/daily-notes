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
  are `reason` (model step), `act` (run a tool), `plan` (one-shot planning).
  Routing *between* agents is not a node — it is the loop's, and no graph has an
  edge to another agent. Neither is pausing: an agent returns `needs_input` and
  the loop owns the confirmation, so no graph holds an `approve` node or a
  LangGraph `interrupt`.
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
- **`graph.py` composes; the agent runs.** An agent's `graph.py` only builds
  and compiles — it holds no `invoke` of its own, and nothing else in the
  package enters a run. The agent's `start`/`resume` calls
  `GRAPH.invoke(state, graph_config)` directly: LangGraph's own signature, no
  wrapper in between. The per-agent bound travels in `graph_config` — a
  `recursion_limit` the agent derives from its own step budget — so the graph
  reads no agent configuration. A graph that compiles without a checkpointer
  carries no `thread_id`: naming a thread nothing saves grows an in-process
  store one dead entry per turn.
- **Extend by data, not by branching.** Prefer a registry/map over a new `if`:
  a new agent is an `AgentSpec` plus one line in `agents/bootstrap.py`; a new
  tool is a file in `tools/<agent>/` registered in that package. Never edit the
  turn loop or an agent's graph to add a capability.
- **Deterministic work belongs in its own node, not inside a write node.**
  Retrieval, classification, and time resolution are separate, testable steps
  (`schedule_resolve`, `link_context`); the write nodes stay
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

  has_interrupts(state_snapshot.tasks)
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
- **A function or method starts with a verb.** A name that is only a noun reads
  as a value, so the call site looks like an attribute access and hides that work
  is happening. Put the verb first — it is the thing the reader is scanning for:

  ```python
  # wrong — these read as fields, not calls
  action_id(correlation_id, agent, tool_name, tool_args)
  registry.roster()
  history.problems(produced)
  history.entry(agent, result)

  # right — the verb says what happens, the noun says to what
  generate_action_id(correlation_id, agent, tool_name, tool_args)
  registry.list_agents()
  history.find_problems(produced)
  history.build_entry(agent, result)
  ```

  Predicates count as verbs and keep their natural prefix: `has_interrupts`,
  `is_expired`, `may_read`, `can_retry`. So do the domain verbs a reader already
  knows — `invoke`, `register`, `save`, `run`, `encode`. The rule is about the
  first token being an action, not about padding short names: prefer `merge` over
  `merged`, and don't turn `save` into `perform_save`.
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
  `notesheet`, `notecard`, `mapview`, `contextmenu`, `addnote`, `header`,
  `search`. These are
  fully isolated — they import only shared *infra* (`db`, `api.deps` for auth,
  `api.media_token`, `file_store`). Each serves its own URL prefix
  `/api/<section>` (e.g. `GET /api/feed`, `GET /api/notesheet/{id}`,
  `GET /api/mapview/graph`, `GET /api/contextmenu/paths`,
  `POST /api/contextmenu/notes/{id}/path`, `GET /api/addnote/{id}`,
  `GET /api/addnote/roots`, `GET /api/addnote/children?root=`, `POST /api/addnote`, `PUT /api/addnote/{id}`,
  `GET /api/header/stats`, `GET /api/search?q=`, and the image proxy
  `GET /api/notecard/attachments/{id}?t=<token>`).
- **`api/chat_v2`** — the chat tab, driven by the **agent farm**
  (`POST /api/chat/v2`, `/api/chat/v2/confirm`). It owns the caller's clock/locale
  *and* the `chat_threads` projection (its own `db`): it hands the thread to
  `agents.bootstrap.farm`, and because the loop returns no message list, this
  section appends the user's message and the responder's reply itself, passes
  prior turns down as `references={"messages": …}`, and stores
  `TurnOutcome.pending` as the handle a later confirm resumes. No `citations` on
  the response yet (see `devdoc/agent-loop.md`). The name keeps the `_v2`
  suffix until the URL is collapsed back to `/api/chat`.
- **`api/telegram_bot`** — the single folder for every bot interaction, all under
  `/api/telegram_bot` (capture text/voice/media, enrich, atomize, polish, delete,
  link-candidates/toggle, reminders + dispatcher, user resolve/settings, RAG
  `search`, `ping`). It owns its full domain in `helper.py` + `db.py`
  (embeddings, one-shot enrichment, reminder parsing, links, user settings, RAG).

There is **no shared domain layer** (the former `services/`/`stores/`/`common/`
are gone). Each vertical duplicates the domain + persistence it needs:
`api/telegram_bot` in its `helper.py`/`db.py`; each agent in the farm owns the
domain it needs (`agents/finder` reads, `agents/enricher` writes notes,
`agents/classifier` files them, `agents/reminder` schedules). Only
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
Enrich button (one-shot enrichment in `api/telegram_bot/helper.py`). There is no
capture-time enrichment agent: `agents/enricher` plans one write per chat turn
and has no capture loop — the interactive graph that would have served one was
deleted unused.

The `api/` service (FastAPI) hosts the section verticals; it is the
backend gateway and **owns schema migrations** — it runs `migrate.run_migrations`
on startup (`api/main.py` lifespan). It deploys separately and its start command
is `python -m api.run` (the image's `CMD`), a dual-stack launcher — binds `::`
with IPV6_V6ONLY=0 so it serves both private IPv6 and the public IPv4 edge. The
API image is built from **`Dockerfile.api`** (single-stage Python — the API is a
pure `/api` gateway and serves no frontend). The Mini App is a **separate static
Railway service** built from **`Dockerfile.webapp`** (Vite build → a Caddy static
server, `browser/webapp/Caddyfile`, SPA fallback to `index.html`); it calls the
API cross-origin (hence CORS + `WEBAPP_ALLOWED_ORIGINS` on the API). Because the
Mini App is a separate origin, **every verb a router serves must be listed in
`allow_methods`** in `api/main.py`: `CORSMiddleware` answers a preflight for an
unlisted method with 400 *before* the route is reached, so a new verb presents
as a broken endpoint with a perfectly correct handler behind it — which is how
`DELETE /api/contextmenu/notes/{id}` first shipped dead.
`tests/test_cors_methods.py` keeps the list in step with the routers. The bot is
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
`GET /api/feed` (full note cards, newest first), `GET /api/explorer`
(`{notes, roots}` — the tree's notes plus the vault's root folders,
localised and in `config.ROOT_FOLDERS` order, which is how the client
orders a top level it only knows as localised path strings) +
`GET /api/notesheet/{id}` (preview), `GET /api/contextmenu/paths` (the
change-path picker's roster), `POST /api/contextmenu/notes/{id}/path` and
`/api/contextmenu/folder/move` (rename a note's or a whole folder's path — root
folders can't be moved), `DELETE /api/contextmenu/notes/{id}` (hard delete),
`GET /api/mapview/graph` (connections map),
`GET /api/header/stats` (root-folder counts: per root, its sub-folders plus
its loose notes, labelled in the user's language), `GET /api/search?q=`
(server-side search), and `GET /api/notecard/attachments/{id}?t=<token>` (the
signed image proxy). `POST /api/chat/v2` + `/api/chat/v2/confirm` back the
**agentic chat tab** (see below).

UI: a **header** with no bar of its own — an **Inbox ring**, the vault's other
root-folder counts (Projects / Areas / Resources) and a **folder-filter**
button, over a progressive blur scrim. The ring is two concentric bands in a
64px box. Inside is the **disc** — 54px, the size the dock's circles use, a
1.5px grey border holding the Inbox count at `.stat b`'s size and weight; it is
always drawn, so an empty Inbox is just a bordered circle with a white `0`. The
count is **SVG `<text>` inside the same `<svg>` as the circles**, not a
positioned `<span>` over them: its `x`/`y` *are* the circles' `cx`/`cy`, so no
inherited `line-height` or stacking can drift it off the centre they are drawn
around (an overlay span did exactly that, sitting low in the disc). `dy="0.35em"`
does the vertical centring rather than `dominant-baseline`, which older WebKit
ignores; digits have no descenders, so that puts the glyph's middle on the
circle's. It is white at every count, zero included — the dashes say how full
the Inbox is, and a number that changed colour too would say it twice. Past
`COUNT_CAP` = 99 it reads `99+` (`lib/format.formatCount`), which keeps the
label inside the disc's ~51px of clear width at one fixed size instead of
introducing a second font size that only renders on counts nobody has.
Outside it, across a 2.5px gap, is the **dashed ring**: 2.5px `--commit`, one
dash per waiting note, capped at `RING_MAX_SEGMENTS` = 12 (128 notes over that
circumference is 0.6px of ink per dash — a solid blur that would look the same
at 90 or 300). At zero the dashed circle is **not rendered at all** rather than
given an empty dash array, which is what makes "nothing waiting" a different
shape rather than a solid ring. A small blue **plus badge** sits centred on the
disc's edge at the lower right, cutting through both bands with a **1.5px white
border** — load-bearing now the dashes share its blue, since a dash crossing it
would otherwise merge into the badge and stop reading as a separate object; it
is the only control — the bands and the count are a readout, because
two hit zones inside one circle is a mis-tap that opens a full-screen page.
Tapping the badge opens the **Add note page**: a full-screen overlay whose own
floating bar replaces the header and dock while it is open, and mirrors the
dock's own composition: two `.fab` circles — ✕ left, ✓ right in `--commit` —
flanking a `.tabbar` pill of three icon-only capture buttons (photo, voice,
reminder: the kinds the bot already accepts, plus the one piece of metadata
worth setting while the thought is fresh). **All three are `disabled`** — the
Mini App has no note-create endpoint, so wiring a photo picker would produce a
file with nowhere to go; dimmed reads as not-yet, whereas a live-looking button
that swallows the tap reads as a bug. It is
**always mounted**, hidden with `opacity: 0` + `pointer-events: none` rather
than unmounted or `display: none`, and that is load-bearing rather than a
transition: neither of those leaves a focusable element, and iOS and Telegram's
webview raise the keyboard only for a `focus()` made *during a user gesture*.
So `openAddNote` focuses the textarea (shared through `AppContext` as
`addNoteInputRef`) **before** it patches state — anything waiting on the
re-render has lost the gesture and gets a caret with no keyboard, which is what
the old `setTimeout`-after-mount did.

**The overlay is sized to the visible viewport**, not the screen:
`lib/format.visibleViewport` returns `{top, height}` straight from
`window.visualViewport` (`offsetTop` included, since iOS scrolls the visual
viewport when the keyboard opens), and the overlay takes them inline with
`bottom: auto` to release the CSS `inset: 0`. Everything anchored to its bottom
edge or its centre then lands above the keyboard by construction, so the bar is
a plain `bottom: calc(30px + env(safe-area-inset-bottom))` with no arithmetic.
This replaced a `keyboardInset` helper that derived a keyboard height by
subtracting the visual viewport from `window.innerHeight` — **the one number
that cannot be trusted here**: iOS does not shrink `innerHeight` for the
keyboard and Telegram's webview resizes its container independently, so the
difference came out near a full page height and threw the bar off the top of
the screen on iPhone. Reading one source removes the class of bug; a test
asserts the helper touches no `window`, `document` or `innerHeight`. Null
viewport (older webviews) leaves the overlay full-screen.
**Saving.** The page's ✓ is wired: `POST /api/addnote` writes a note typed on
the page and `PUT /api/addnote/{note_id}` saves an edited one, chosen on the
client by whether it has a `note_id` — two verbs rather than one "upsert",
because a POST that silently updated (or a PUT that silently created) is an
endpoint nobody can reason about from the call site. Both carry `{text, path,
tags}` and answer with the stored note. `tags` is always `[]` for now (its
button is still disabled) and `path` is sent as the user left it: empty means
the API files the note under the default root, which is why the button lights
only for an actual choice and why the client must not invent a folder name
here — that was the retired `defaultRoot` behaviour.

On the client the tick is `disabled` while a save is in flight **and** when
there is nothing to save, with the same `canSave` guard inside the handler:
`disabled` is the visible half, but a tap already dispatched before the
re-render would otherwise run the sequence again and create the note twice.
An empty note cannot be saved at all — the API requires one character, so that
would be a 422 the user cannot act on, and a dimmed tick says "not yet" where
an error says "something went wrong". A **failure keeps the page open** with
the text still in the field and reports itself on the same `.addnote-error`
line the failed *read* uses (the two cannot both apply: a note that failed to
load has nothing to save); only a 422 gets a specific message, since the
folder is the one thing the user can fix from here. On success the page closes
and `reload()` runs — the feed, explorer, map and header counts all derive
from the boot fetch, so that is the one path meaning "the vault changed", the
same one the ⋮ menu's path change and delete take. `tests/test_addnote_api.py`
also checks the two sides against each other: the fields the page sends, the
fields it must not, and that neither save call carries the `.catch` every read
in `api.js` has. The payload deliberately has **no
`linked_note_ids` and no attachments**: the page displays a note's neighbours
and has no control for changing them, so a save that rewrote the link graph
from a read-only list would be the worst kind of surprise, and there is still
no way to add a photo. `PUT` is a new verb for this API, so it had to join
`allow_methods` in `api/main.py` — the Mini App is a separate origin and
`CORSMiddleware` answers an unlisted method's preflight with 400 before the
route is reached.

**Both writes rebuild the note's chunks.** `note_chunks` is what search, RAG
and the link suggestions actually match on, so text saved without them is a
note that reads correctly everywhere and cannot be found by what it now says —
and nothing reports that. It runs on every save rather than only on a text
change: the editor has no reliable dirty signal, and a redundant re-embed is
cheaper than a silent mismatch. The sequence is **spelled out in each route**,
not shared: every step is I/O, the two routes differ in more than they share
(one inserts and answers 201, the other updates and can 404), and the helper
that briefly owned it is the cautionary tale below.

**Two orderings carry the correctness**, and both exist so the step that can
fail cannot take the user's writing with it. The row is written *before*
`embedings.build_chunks`, so an OpenAI failure costs the note its
searchability and not its text — logged and swallowed, since reporting an
error would tell the user their text did not save when it did. And
`db.replace_chunks` is called from the `else:` of that `try`, so a failed
build leaves the **previous** chunks in place (matching the old wording beats
matching nothing); inside it the delete and the inserts share one `cursor()`,
because a delete that commits without its insert is the same bug by another
route.

**A cautionary tale, kept here because the suite did not catch it.** The
rebuild first lived in `helper.rebuild_chunks`, which called
`db.replace_chunks` while importing no `db` at all — a guaranteed `NameError`
on the first save, shipped green. Every assertion around it compared *strings*
in the source, and the one test that imported the module never called the
function. Two guards came out of it: `tests/test_section_imports.py` imports
every section's modules and walks their ASTs for names nothing provides (with
a probe asserting the check still catches that exact shape), and
`tests/test_addnote_save.py` **executes** both routes against a recording fake
`db` and a patched embedder. The architectural half of the lesson is the
reason it could happen: a `helper` allowed to reach for the database is a
`helper` that can forget to import it, so this section's `helper.py` now holds
only `attachment_views` and the pure `clean_root_path` / `clean_tags` rules,
and every database call and the embedding round trip live in `endpoints.py`.

An empty `path` is **not an error** — it is "wherever notes go", resolved to
`config.DEFAULT_ROOT_FOLDER_KEY` in the caller's language, so a note saved from
this page always lands somewhere. A path outside every known root is a 422; one
written in another supported language is accepted, because a user who switched
languages still has paths in the old one. `helper.clean_tags` trims, drops
blanks, de-duplicates case-insensitively keeping the **first** spelling (so
"Work" survives a later "work"), preserves the user's order, and caps at
`TAGS_MAX` = 5 by truncating rather than refusing.

A saved note is left **untitled**. `title` is enrichment's field — an LLM's
one-line summary — and a title the user never wrote would be a guess presented
as theirs; every read vertical already maps an absent title to a text snippet
(`_display_title` in feed, explorer, notesheet, mapview and search), so an
untitled note reads as its own first words everywhere.
`tests/test_addnote_save.py` checks that claim rather than assuming it, along
with both orderings and the columns the update does *not* write — `title`,
`note_type` and `priority` stay enrichment's.

The response is read back from the database rather than echoed from the
request: the path that was sent is not the path that was stored (an empty one
became the default root, a typed one was normalised), and a client trusting its
own input would show the wrong folder until the next open.

**The editor reads its own section.** `GET /api/addnote/{note_id}` (the
`api/addnote` vertical: `endpoints` → `helper` → `db`, its own SQL, shared
infra only) returns `{id, text, path, tags, attachments, linked_note_ids}` —
everything the page's controls own, so wiring one of them later is a UI change
rather than a UI change plus another round trip. The writes belong here beside
the read when they arrive. The owner predicate is **in the query** (`WHERE id =
%s AND user_id = %s`) rather than a check afterwards, a miss is a 404 for both
"no such note" and "not yours" (so the endpoint is not an oracle for which ids
exist), and the attachment and link reads happen only *after* that check
passes — an id that is not the caller's never reaches them.

`path` and `tags` ride along in the note's own row; a second query for two
columns already in hand would be a query for nothing. `attachments` are
`{id, kind, mime, url}` where `url` is the **signed notecard proxy path**,
relative, minted per request — the bucket is private, an `<img>` cannot send
the initData header, and `note_attachments.storage_key` is neither selected nor
mapped, because a bucket key in a payload is one someone will try to fetch
directly. The URL template and the `media_token.sign` call are duplicated from
the feed section rather than shared, which is this codebase's deliberate trade;
signing reads the clock and a secret, so it happens in the endpoint and its
result is passed *into* the mapper. `linked_note_ids` is the **union of links
and backlinks** — directed edges, backlinks being the reverse query, so a
note's neighbours are both directions, the same set the card's chips show — and
the `user_id` predicate sits on the *far* endpoint of each edge so a link into
someone else's note cannot leak its id. They come back `sorted`, because
`UNION` promises no order and an unordered payload makes two reads
undiffable.

The response is built **in the endpoint**, not through a mapper. Three
columns are nullable where the client needs a value — `text` and `path` feed
*controlled* React inputs (where `null` means uncontrolled: React warns and the
field stops tracking its own state) and `tags` is a nullable jsonb rendered
with `.map`, which throws on `null` — so each passes through one `or` at the
place that already owns the reads. A helper for `value or ""` would be a name
to read past; `helper` keeps only `attachment_views`, which earns its place by
being impure. The row is **not** spread into the model (`EditableNote(**row)`
would hand the coercion to whatever the row happens to hold); Pydantic ignores
the unlisted columns and copies the lists, so nothing is smuggled into the
payload and nothing the caller still holds can change it afterwards. On the
client the extra fields are held in state and **not rendered**: the
path/link/tags buttons stay `disabled` until each has an editor and there is
somewhere to save it.

The read happens **after** the page is open, and that order is forced rather
than lazy: the keyboard rises only for a `focus()` inside the opening gesture,
so `openAddNote` focuses synchronously and nothing can be awaited first. Two
things follow. Loading shows a `"Loading…"` **placeholder** rather than a
spinner — the field is already focused and under the user's eyes, and
*disabling* it would drop that focus on iOS and cost the keyboard the gesture
was for. And the response must never overwrite what was typed in the gap
(`setText((typed) => typed ? typed : note.text)`): the keystrokes are newer
than the response, and a textarea that erases itself a second after opening is
the worst failure available here. A stale response from a previously opened
note is dropped by the effect's `live` flag. A failed read leaves the page
**open** with an inline message: closing mid-gesture reads as a crash, and a
blank editor with no message is indistinguishable from a note whose body really
is empty. `tests/test_addnote_api.py` and `tests/test_addnote_loading.py` pin
the tenancy, the null-body mapping and each of those three decisions.
A column of `.fab` circles runs down the **right edge**, centred as one group —
the container carries the centring, not any button, so it stays balanced as the
column grows. They are **46px**, 15% off the dock's 54, scoped as
`.addnote-side .fab` because `.fab` is shared and an unscoped size would shrink
every circle in the app; the glyph and gap scale with it (20→17, 12→10). At the
top, set apart by a wider gap rather than a different shape, is an inert **AI**
button — it acts *on* the note where the rest describe it. Below it, **path /
sub-folder / tags** (the first two live wheels, tags still `disabled`). They are plain circles rather than a capsule: every
control on this edge is the same `.fab` as the ✕ and ✓. The
**reminder** button stays in the bottom capture pill despite being metadata
too — moving it would churn a bar that is already settled. In the **top-right
corner** is the **help button**, opening
`MarkdownHelp.jsx`. It carries no glass and no ring — its glyph is already a
circled `?`, so any chrome would be a second circle around the first — and it
needs no top padding on the textarea, because the 74px right padding that
clears the mode circle already keeps text 74px from an edge the button only
reaches 48px into. The cheat sheet hangs below it at `right: 0`, growing
*leftward* rather than off the corner it is pinned to. That sheet is
**Ukrainian only and hard-coded**: the Mini App has no
i18n layer, every other label being fixed English or translated server-side,
and a second translation table beside `locales.json` is one more thing to
drift. Its examples are hand-styled rather than rendered (no renderer yet), and
it documents **no underline** — Markdown has none, and the only route to one is
raw HTML this app never renders.

A trap worth knowing: `pointer-events: none` on the overlay does **not**
disable a child that sets `auto`, so every control inside the always-mounted
page is scoped to `.addnote.show`. Unscoped, the closed page's buttons stayed
live over the feed and a tap where Done sits fired Done.
`tests/test_addnote_keyboard.py` pins the inset maths, the focus path, the
`.show` scoping and the cheat sheet.

Growing the box from 54 to 64px does **not** disturb `.hdr-filter`'s -11.17px
lift: both it and the stats are centred in the header row, so the offset
between them is independent of row height. `/api/header/stats` returns all four
roots and the client picks Inbox out **by key**, so changing root order
server-side moves columns rather than silently dropping one. The dash geometry
and the label are `lib/format.ringDashes` / `formatCount` (pure, tested under
node in `tests/test_inbox_ring_js.py`): the gap absorbs the round line caps,
which paint half a stroke width past each end of every dash. A floating
glass **dock** holds a center pill (Notes / Map / Explorer icons, in that order)
flanked by two circle buttons — chat (left) and search (right). Tapping a circle
swaps the pill's icons for a shared input bar (with a Send button) and the pill
widens toward the borders; the active circle's glyph becomes a ✕ and doubles as
the close/back control (the opposite circle hides). Views: **Notes** (a feed of
note cards), **Explorer** (folder tree), **Map** (canvas force-directed graph),
**Search** (client-side filter over loaded notes), **Chat** (conversation view
over the `/api/chat/v2` seam). One card template (`buildPost`) is shared by the
feed and the bottom-sheet preview (opened from the explorer/search/graph):
image carousel on top, then **the note's own text**, then the date row (sharing
its line with the `⋮`), path, tags, and a de-duplicated row of linked-note
chips (each labelled with that neighbour's opening words) (depth-1 neighbours; tapping one navigates without recursion). The text
leads because it is what the user wrote — the date, path and tags are the
machine's description of it, so they follow rather than precede it. The dashed
divider moved with that: it sits above `.post-head`, where the user's words end
and the description begins, instead of above a body that is now the first thing
on the card.

Text past `CLAMP_CHARS` = 100 characters is cut with an **inline "… more"**
(`lib/format.clampText`, pure and tested under node), not a button: the control
belongs to the paragraph it interrupts, where a button would read as an action
on the note like Enrich or Link. The cut retreats to the last space inside the
budget so no word is sliced in half — unless there is no space to retreat to (a
URL), which is cut at the limit rather than shown whole. An empty `rest` is the
signal that there is no control to render, so the component never compares
lengths itself; expanding renders the **original string** rather than
`head + rest`, because the split trims the seam and re-joining would eat a
space. "less" collapses it again — a feed of expanded notes is a feed you
cannot skim. The clamp applies in the preview sheet too, keeping one template.

The linked-note row carries **no heading**: a row of 🔗-prefixed chips says
what it is, and "No linked notes yet" was a line of text reporting the absence
of something the user had not asked about. Nothing renders when there are none.

**The card shows no title**, and neither does anywhere else in the web app
bar the map. `notes.title` is an LLM-written one-line summary: enrichment still
writes it and the bot still shows it, but a *list* of titles is a list of the
model's words where the user is looking for their own, so every browsing
surface labels a note with the first 60 characters of its own `text`. Four
sections do that in a `_note_label(text)` of their own — `feed`, `explorer`,
`notesheet`, `search` — each with the same `LABEL_CHARS = 60`, so a link chip,
an explorer row, a search hit and the sheet's linked notes all read alike,
whatever each then clips to in CSS. The payload field is called **`label`**,
not `title`, because the value is a cut of the text and a field named `title`
would be a lie the next reader believes; the `title` column is no longer
*selected* in those sections' SQL either, since data flowing through a payload
unread reads as a live field. "untitled" survives as exactly one case: a note
with no text at all (one that is only photos).

`mapview` is the **deliberate exception** — its cards are a few dozen pixels
wide, where a 60-character opening is unreadable and a summary is the only
thing that fits — so it keeps `_display_title` and its `title` key.
`NoteMiniCard` is shared between the chat (fed by `notesheet`, so `label`) and
the map (`title`), and reads `note.label || note.title` for exactly that
reason. One more title remains on screen: the **chat's link picker**, whose
candidates come from the agent farm rather than a read section.
`tests/test_note_labels.py` runs each section's label, pins the field name and
the dropped column, asserts the exemption stays one section wide, and counts
that remaining `c.title` so it cannot quietly become two.

Two consequences worth stating. The explorer's tree now **sorts by the label**,
so rows read alphabetically by how each note opens. And `search` still *matches*
on `title` while never showing it — an enriched title often holds a word the
note itself does not, and dropping it from the predicate would make those notes
unfindable — so a hit can match text its row does not display. Path/localised-root names are written by the LLM
into the note path and stored localised (not translated at display time). The `⋮`
menu on a card/folder opens a context menu to change its path (**Path**), and — **on notes
only** — to delete.

**One icon style, including in the `⋮` menu.** Every glyph in the app is a
24-viewBox inline SVG with `fill: none`, `stroke: currentColor` and a 1.8
stroke — the dock's tabs, the pill's Send, the Add-note page's side buttons,
and now the context menu's Edit / Path / Delete, which used emoji
(✏️ 📁 🗑). Emoji fail three ways here: they render in a different style on
every platform, so one menu looked imported from elsewhere; they carry their
own colour, which left the Delete item's label red and its glyph grey; and they
sit on the text baseline rather than in a box, a few pixels off centre beside a
14px label. `currentColor` fixes the second for free — the danger row colours
the whole item and the glyph follows. `.ctx-item` is a flex row with the glyph
at `flex: none` so labels all start on the same x and a long one can't squeeze
the icon. The folder glyph is deliberately the same path as `AddNote`'s path
button: the same object is not drawn two ways.
`tests/test_contextmenu_icons.py` pins the recipe, the shared folder path and
the absence of emoji.

**The path picker is a combobox, not a dropdown.** `GET
/api/contextmenu/paths` returns every root folder — **including the empty
ones**, since an empty root is exactly where a note gets moved and typing it by
hand is what the picker exists to avoid — plus every path the user already
files notes under, ordered by `config.ROOT_FOLDERS` and then alphabetically,
with a root sorting above its own children. A path under an unrecognised root
(one left behind by a language switch) sorts last rather than being dropped,
which would hide the only route back to those notes — the same choice
`lib/format.compareRoots` makes client-side. The endpoint resolves the locale
and reads the rows; `helper.known_paths` is a strict pure mapper over both, per
`api/README.md`. Root labels are **one language at a time**
(`helper.root_labels`): `clean_root_path` still accepts a root typed in any
supported language, but four translations of Inbox in a list is noise.

The sheet behind the menu's **Path** item (the label is just "Path" — the
sheet's own heading says whether it is a note's path or a folder's) has a
single input that is both the filter and the answer. On open it is
focused **and selected**, not just focused: a path is more often replaced than
edited, so the first keystroke or Backspace clears the whole thing, while the
old path stays readable until then — clearing the input on open would throw
away the only reference to where the note currently lives. The selection waits
out the sheet's 60ms slide-in, because focusing mid-transition lands the caret
in a moving element on iOS. **The list stays hidden until the input is
touched** (`touched`, reset on every open): on open the input holds the current
path, so a list filtered by it would show that path and its children — the one
place the note already is — and the sheet would open at its tallest for no
information. Typing, clearing and picking a row all go through one `edit`
helper, so no route can set the value while leaving the list hidden. A `✕`
inside the field empties it in one tap (which opens the list: an empty query is
every path) and is rendered only when there is something to clear, never hidden
*under* the thumb that is reaching for it. Typing narrows the scrollable list
(`lib/format.filterPaths`, case-insensitive); tapping a row *fills the input*
rather than saving, because the common move is to pick a folder and then extend
it (`Projects/api` → `Projects/api/v2`). Text matching
no row is simply a new path — the server validates the root either way, so
there is no "new folder" mode to switch into. In folder mode the target's own
path and its descendants are filtered out (`lib/format.selectablePaths`): a
folder cannot become a child of itself, and renaming it to itself is a tap that
reports success and changes nothing. The exclusion tests for the slash, so a
sibling like `Projects/apiv2` survives. A failed roster read costs the
suggestions, not the ability to move a note — `listPaths` falls back to an
empty list. `tests/test_path_picker.py` pins the ordering, the empty-root rule,
the unknown-root tail and the subtree exclusion.

**The path wheels.** The Add-note page's folder control is two buttons — root
folder and, one level below it, sub-folder — over the one `path` string the
save still sends (`""` | `Root` | `Root/child`; the backend's create/update is
untouched). Each has its own read, split so choosing a root costs a read of that
root's notes rather than the vault: `GET /api/addnote/roots` serves the fixed
root folders in canonical order (empty ones included — an empty root is where a
note gets filed) plus `default_root`, with no per-note query at all, and `GET
/api/addnote/children?root=` serves the distinct second-level names already in
use under it, filtered in SQL by `split_part` (a whole-segment match — `LIKE
'Projects%'` would also catch `Projects2/x`), owner-scoped. `root` is not
validated against today's roster, so a root left behind by a language switch
still shows its children. The reads are **duplicated from `api/contextmenu`'s
idea** rather than imported (same trade as the duplicated `db.py`), and both
routes are **declared before `/{note_id}`**, which is load-bearing: FastAPI
matches in declaration order, so the other way round `GET /api/addnote/roots`
is answered 422 by the note handler — a broken feature with a correct endpoint
behind it, exactly how `DELETE /api/contextmenu/notes/{id}` once shipped dead.
`default_root` is `config.DEFAULT_ROOT_FOLDER_KEY` localised, read from the
*key* rather than from the roster's first entry, because the order and the
default are two decisions and the day they disagree, position 0 would file notes
somewhere else in silence.

On the client the buttons are views of `path`'s first two segments; **the
sub-folder is `disabled` until a root exists**, picking a *different* root
replaces the whole path (a stale `Projects/api` never survives a move to
`Areas`) while re-picking the same one keeps it, and a sub-folder pick sets
`root/child` — second level only, so picking one on a deeper loaded note
truncates it. Until a wheel changes it a deeper loaded path is kept as is. Only
the sub-folder wheel `allowNew`s a typed name (the server rejects an unknown
root with 422, so offering one would end in an error), and slashes are dropped
as typed. One `PathWheel` serves both, given `load` and `allowNew`. The old
`link` button is gone; its slot became the sub-folder button, drawn as `/..`
(a stroked slash and two dots), and the `tags` button is a stroked `#`.

**A drum with no panel.** The options scroll in a transparent column beside
the button. There is deliberately **no container** — a panel would be a second
floating object competing with the bar the wheel hangs off, over a page that is
already glass over the note's text — so the rows are the whole control. Each
sits *above* the page rather than being a dark hole in it: `--bg-elev`, a
`rgba(255,255,255,.12)` hairline so the note's text behind cannot bleed through
the edge, and a soft lift. No blur, because a row is not a floating bar. A row
is **as wide as its name** (`width: auto` with `align-items: flex-end` on the
track), which is what makes the column read as a list of folders rather than a
stack of bars; `max-width` keeps the long ones in the column and the label's
left-side ellipsis takes over from there. Rows are plain text — they had a
7px dot in the folder's hue (`lib/format.pathColor`), dropped because a handful
of short names needs no second cue. The chosen folder is
**filled blue**, a deliberate exception to "`--commit` as a fill means an
affirmative action": in a list where every row is a candidate, the one that is
already the answer has to be unmissable, and a hairline would be lost among
rows that have borders of their own (white on that blue clears 4.5:1, which
`tests/test_commit_colour.py` checks).

A trap worth knowing: `overflow-y: auto` on the track computes **`overflow-x:
auto` as well**, so the arc's leftward bow was clipped by the scroll box's own
left edge — which looked like a frame cutting the rows off. `padding-left` on
the track (greater than `WHEEL_REACH`, with `box-sizing: border-box`) is the
bow's room inside the scrollport. What survives of the old chrome is the arc. `lib/format.wheelItem` computes `t = √(1 − (dy/r)²)` — the circle's
own equation — and that one value drives everything: each row bows out by
`t * WHEEL_REACH`, scales between .78 and 1, and takes `t` as its opacity, so
the fade is **circular rather than linear** (bright near the centre, diving at
the rim, where `t` reaches exactly 0 and stays — the `ratio >= 1` guard, since
`√` of a negative is `NaN`, a blank style and a row that never disappears).
`reach` and `radius` are separate parameters because at `reach = radius` the
centre row would shift half a phone. The fade is **per row, not a mask on the
column**: it has to follow the rows along the arc. Rows past the rim drop their
`pointer-events`, or the wheel's dead space stays tappable, and
`.path-wheel-opt` scales from `transform-origin: 100% 50%` so it grows away
from the button rather than drifting sideways.

**The fade works two ways, and needs to.** The per-row opacity follows a row
along the arc — it is the wheel turning away from you — while a `mask-image` on
the track fades the last 40px at each end, pinned to the *visible boundary*. A
row sitting at the edge therefore dissolves into it whatever the geometry says,
and the two ends look like siblings. The mask is `-webkit-` prefixed as well,
since Telegram's webview is WebKit and a missing mask is precisely the bug this
replaced.

**The filter is row 0 — on the sub-folder wheel only.** The root wheel is the
vault's handful of fixed roots and takes no typed name, so it has no filter and
its options start at row 0 (`lead` is 0 there, 1 where there is a filter). It
wears the same pill as every option, so typing a new
path is an *option* rather than a mode — text matching nothing appears as an
ordinary row above the matches and selecting it is how you use it (Enter does
the same). It takes the arc unmodified. It used to carry an opacity floor so it
could not be missed, and because it is the *topmost* row that made the top of
the wheel the one edge where nothing ever disappeared — which reads as a broken
fade rather than as a helpful control. It is findable the way every other row
is: by scrolling to it. Where there is a filter, option `i` is row `i + 1` —
including in the scroll that centres the current path.

**The box runs one row longer than it reads.** `WHEEL_HEIGHT` is 336 — six
rows of 56 — for five *legible* ones, because the mask fades 40px at each end
and leaves the outermost row on either side mid-dissolve. Sizing the box to
exactly the rows you want to read is what left the fifth permanently
half-faded. The fade has to stay shorter than one row, or it eats into the
second row in and the count is wrong again.

**Row pitch is split across two files and has to add up.** `WHEEL_ITEM_HEIGHT`
is 56 in JS; the CSS pill is 44px with 6px margins. Nothing at runtime notices
if they diverge — the wheel just drifts out of step with its own scroll
positions — so `tests/test_path_wheel.py` adds them up. The height is *not* set
inline, which would force an `!important` in the stylesheet to win it back.
And `.path-wheel-track` is a **flex column** for a non-cosmetic reason:
adjacent block siblings collapse their vertical margins, so 6px + 6px would
become 6px and every row would sit 50px apart while the maths assumed 56.

**Labels clip on the left.** `direction: rtl` on `.path-wheel-label` moves the
overflow and the ellipsis to the *start* of the line, so a long path keeps its
leaf — the part that tells two folders under one root apart — and loses its
stem. The text sits in a `<bdi>` so the bidi algorithm still lays
"Projects/api" out left to right; without it the `/` characters are neutral and
migrate. `min-width: 0` lets the flex child shrink at all (its default
`min-width: auto` is its content, so the pill would grow instead of the text
clipping), and the pill's `overflow: hidden` catches the rest. This replaced a
22-character cap in JS, which could only guess at pixel width.

**A set folder lights the ring and the glyph, not the fill.** `--commit` as a
*fill* is the app's one affirmative-action colour, so a filled blue circle here
would read as a button that does something rather than a field holding a value;
`.addnote-side .fab.set` takes it as `color` + `border-color` only, and the
glyph follows because the icons stroke `currentColor`. The button lights only
for an **actual choice** — the note's own path, or one the user picked. The
default destination does not light it: nobody chose, `path` stays `""`, and the
save (when it exists) applies `default_root`. Nothing persists yet, so the
choice is cleared with the page. `tags` stays `disabled`: it now
has its data from the note read, which is not the same as having an editor
for it. `tests/test_path_wheel.py` pins the geometry's properties — circular
falloff, zero at the rim, symmetry, the scale floor — rather than its formula.

**The sheet's grip stays put while the sheet scrolls.** It is a normal child
of the scrolling `.sheet`, so it used to scroll out of sight — most visibly on
a note with a photo, which is the case tall enough to scroll at all. `position:
sticky` is only half of it: the sheet's own `14px 18px` padding is *inside* the
scrollport, so content travels through it above and beside a narrow 36px bar.
So `.sheet .grip` is now the full-width band — negative margins cancel the side
padding, it carries the sheet's background and rounded top corners, and it
sticks at `top: -14px` to cover the top padding — with the 36×4 pill drawn as
its `::after`, centred inside. `tests/test_notecard_layout.py` asserts the
negative values specifically, since they are the part that looks like
redundancy worth simplifying away.

**Delete is hard and unconditional.** `DELETE /api/contextmenu/notes/{id}`
removes the note whatever its state: filed, linked, or carrying a reminder that
has not fired. That is the opposite of the bot's `delete_if_bare`, which refuses
all three, and the difference is the point — one is a cleanup, this is the user
asking. Chunks, attachments, links (both directions) and reminders go by
cascade; the attachment and voice objects are removed from the bucket, which
does not cascade, so `helper.delete_note` reads the keys **before** the row
delete — afterwards `note_attachments` is gone and the objects are unidentifiable.
A key that won't delete is logged as an orphan and does not fail the request:
the row is already gone, so reporting failure would tell the user the note
survived. The `user_id` predicate on the DELETE is the tenancy guard, and 404
covers both "no such note" and "not yours". Folders get no Delete: a folder is a
path prefix rather than an object, so it would silently mean "destroy everything
filed under this". Confirmation is an in-app sheet (never `window.confirm`,
which some Telegram webviews suppress outright) with a generic irreversibility
warning and a red button. `--danger` (#d0343a) is the fill and `--danger-text`
(#ff6b6b) the label on dark, because neither clears 4.5:1 in the other's role —
`tests/test_contextmenu_delete.py` asserts both ratios.

**Colour means one thing each.** `--commit` (#2f6feb) is worn by **every**
affirmative control and nothing else — the pill's Send, chat's Confirm, the
change-path Save, the Add-note tick, the header's plus badge — so "the blue one
does the thing" is learned once and holds everywhere. `--accent` (violet) means
*state* instead: an active filter, a note's path. `--danger` means destruction.
The split only pays if it is absolute, which is why Save moved off violet, and
why the blue is a variable rather than the eleven hex literals it used to be:
one of them would eventually have drifted. `tests/test_commit_colour.py` walks
the affirmative selectors, fails if any takes `--accent`, fails if the hex
reappears outside its `:root` declaration, and checks white still clears 4.5:1
on it.

A note with no `path` is not in the vault yet: `feed`, `explorer`, `mapview`
and `search` all filter it out (`mapview` on both its edge and its node query,
or the graph draws a node whose detail never arrives). `notesheet` and
`notecard` do **not** filter, so the note stays openable by id and a
`[[note:ID]]` card still renders; neither do the chat agents or the bot's RAG,
so an un-filed note remains findable and one enrichment away from appearing.

"Upcoming" reminders require `remind_at >= now()` as well as a pending status,
in `tools/finder/db.upcoming_reminders` and the bot's, plus the count beside
the list. `agenda_reminders` keeps its own explicit range (a past window is a
fair question) and the dispatcher keeps `remind_at <= now()`, which is the
opposite direction and the whole point of it.

Root folders have one canonical order, the `order` value in
`config.ROOT_FOLDERS` (steps of 10). `common.helper.order_root_keys()` is the
only source of it: `/api/explorer` ships it to the client as the root roster and
`api/header` takes the first four for its counts, so neither restates it.
`lib/format.compareRoots` sorts known roots by the roster and anything
unrecognised — a root left behind by a language switch, say — alphabetically
after, rather than dropping it and hiding notes.

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

## Agentic chat — the agent farm

The chat tab is served by a **farm of peer agents behind a loop**
(client-agnostic, in `agents/`) — see `devdoc/agent-loop.md` for the design and
`devdoc/agents-architecture.md` for the map. No agent knows another exists.

**The turn.** `api/chat_v2` calls `loop.run(message, context, references)`.
The turn loop asks the router who runs next, hands that agent an `AgentRequest`,
saves the `AgentResult` as a row in `agent_states` (the turn tree, migration
0022), folds it into the turn history, and repeats until an agent needs the user
or the reply has been written. The loop is `agents/runtime/loop.py`; who runs
next is `agents/router/`. They meet only in `bootstrap.py` and never import
each other. `AGENT_MAX_HOPS` bounds the turn and counts the
reply.

**Routing** is `agents/router/agent.py`, a registered agent like any other —
same `SPEC`, same `AgentRequest`, and its own row and `HistoryEntry` when it
runs. Cheapest case first: the responder is taken unconditionally when the turn
is finishing; otherwise a caller-supplied `entry_agent` names it for free
(nothing supplies one today); otherwise the
loop runs the router hop and `ROUTER_MODEL` picks from the whole roster. An
agent that already ran is still a candidate — a turn often needs the same one
twice (create a note, then link it), so what has run reaches the router as
history rather than as a filter, and the prompt asks for `null` once the request
is carried out. Each hop is its own `HistoryEntry`; the one entry that is
replaced rather than appended is a `needs_input` the same agent is resuming.
The router reports its choice the way every agent reports its work — a
`Ref(AGENT_KIND, name)` in `produced` — and declines rather than guessing (a
decline produces nothing and the responder takes the hop). Two agents are never
candidates for that choice: the responder, which takes the last hop by
construction, and the router itself, which would otherwise let a decision pick
itself. Router hops don't spend the budget, so `AGENT_MAX_HOPS` still buys the
same work. Adding an agent is a spec plus a line in `agents/bootstrap.py` — the
only module that names an agent — and never an edit to the loop.

**The agents.** `finder` reads and answers (`tools/finder/`: `search_notes`,
`get_note`, `neighbors`, `list_reminders`, `list_agenda`, `list_paths`,
`detect_reminder`); `enricher` owns note writes — create, move, tag, link;
`classifier` owns filing one note in a single pass (type, title, path, tags,
priority) and is the only holder of `enrich_note`; `reminder` owns scheduling;
`responder` is the only one that writes prose to the user. The enricher's and
classifier's descriptions are written against each other, because the router
tells them apart on those sentences alone. A work agent puts its
output in `AgentResult.state` and reports what it touched as typed
`Ref(kind, id)`.

**A hop reads what the turn already found.** The history carries refs, not
prose, so an agent reaches an earlier hop's state through the `read_state`
tool. Every agent but the router holds `may_read = ("*",)` and reads
deterministically before its model call — the router has no tool path. What
separates them is the *fields* each keeps: the enricher and reminder take
`answer`, `citations` and `retrieved_chunks` into `PlanRequest.prior_states`, so
a write is planned against a search that already ran instead of repeating it;
`trace` is never taken, because it records which nodes ran rather than what was
found. The allowlist catches a mistake — a copied adapter reaching for a state
it never meant to — not a lying agent; the tenancy check in `db.get_state` is
the guard that holds unconditionally. `read_state` is duplicated per vertical,
like `db.py`, so one agent's tool surface cannot ripple into another's.

**Writes always pause.** An agent that wants to write returns `needs_input` with
an `ask`; the section stores `TurnOutcome.pending` and
`POST /api/chat/v2/confirm {approve}` resumes the turn. The write runs at most
once — keyed by its own fingerprint in `action_executions`, not by the hop — so
a retried confirm replays the stored outcome. A decline runs nothing. The
responder still takes the last hop on a suspended turn, and its prompt carries
the paused agent's own `planned.summary` — pulled out of that agent's state
rather than handed over by the loop, so the responder keeps no private channel —
because a reply that doesn't say what is being confirmed leaves the user in
front of Confirm/Cancel with nothing to go on.

**Thread state** lives in `chat_threads` (`api/chat_v2/db.py`, migration 0019)
and belongs to the section, not to any agent: the loop returns no message
list, so `api/chat_v2` appends the user's message and the responder's reply and
passes prior turns down as `references={"messages": …}`. `POST /api/chat/v2`
returns `{status:"answer", reply}` or `{status:"confirm", action}`.

`api/telegram_bot` retains its own independent reminder detection, creation and
delivery, and does not use the farm.

**Contracts.** Every shape the farm exchanges lives in `agents/contracts/`, one
type per module (`agent_spec.py`, `agent_request.py`, `ref.py`, …), imported
from the package rather than the leaf: `from agents.contracts import AgentSpec`.
`UserContext` is the turn's clock and owner, and there is exactly one of it:
plain JSON so it survives `agent_states` and a later confirm, carried unchanged
into each agent's graph state. `build_context` makes one, `restore_clock` turns
its strings back into a `datetime` and a `ZoneInfo` at the point a tool needs
them. Each agent used to keep a parallel class of its own and they had drifted —
one serialised a missing timezone as the string `"None"` — so the type and the
two functions are shared, which is safe because they are pure.
The package imports nothing — not an agent, not a tool, not the loop, not
`db` or `config` — and that is load-bearing: it is why four agents plus the
loop, the router and the store can agree on shapes without importing each
other. `tests/test_agent_structure.py` enforces both the no-imports rule and
one-type-per-file.

**Agent tools.** Concrete tool implementations live in the root-level `tools/`
package, not inside `agents/*/tools`: `tools/finder/` for reads, `tools/enricher/`
and `tools/reminder/` for writes. `read_state` lives in each vertical that
calls it — enricher, reminder and responder — duplicated for the same reason
`db.py` is. Each tool file exposes `invoke(context: dict, args: dict)` and
returns `ToolResult` with typed `data: dict`; specs stay with their namespace as
`tools/<agent>/specs.py`. Agents execute them through
`agents/runtime/execute_tool.py`, and callers render `ToolResult.data` to JSON
text only at graph/API boundaries. Extend by adding a tool file and registering
it in its package — never by editing the loop.

**Citations.** `search_notes` returns a `ToolResult` with `data`, `citations` and
`retrieved_chunks`; tools never mutate a turn context themselves.
`agents/finder/state.py` owns the mapping and merge helpers (`tool_context`,
`apply_tool_result`), and the finder reports each cited note as a `Ref`. The v2
response does **not** yet carry citations — `TurnOutcome` has no agent state, so
the chips are unavailable to the endpoint; inline `[[note:ID]]` markers still
render, since the client fetches those by id. The finder writes those markers
into its answer, but the responder is what the user actually reads, so the
responder's prompt requires it to carry every marker through verbatim, one per
line — rewriting a marker into a note's title silently drops the card. See
`devdoc/agent-loop.md`.

## Design docs

`devdoc/` holds implementation specs as Markdown — what is true now, or what has
been agreed but not yet built. Before implementing a feature, check `devdoc/` for
an existing spec and follow it; when a spec is fully implemented, update it, and
when the code it describes is deleted, delete it.

- `devdoc/agent-loop.md` — **the architecture doc for the farm**: contracts,
  the three routing cases, the turn tree, `read_state`, idempotency, and the
  phases it was built in. Start here.
- `devdoc/agents-architecture.md` — the map: which folder is what, and the rules
  that keep it extendable.
- `devdoc/agent-workflows-langgraph.md` — the graphs *inside* agents (finder,
  enricher, reminder), and why LangGraph persists nothing: `agent_states` is the
  only durable record of a hop.
- `devdoc/agentic-enricher.md` — the note action/enrichment agent.
- `devdoc/agentic-classifier.md` — the filing agent split out of it.
- `devdoc/agentic-reminder.md` — the reminder agent.
- `devdoc/action-idempotency.md` — how a confirmed write runs at most once.
- `devdoc/plugin-capture-tokens.md` — **not yet built**: personal access tokens
  + a public `/capture` for plugin clients (Chrome/Codex/Claude).
