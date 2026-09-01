# API service

A separate, independently deployable service that fronts the same domain layer
the Telegram bot uses (`note_service`, `search_service`, `reminders`, `links`,
…). It lives in this one repo (monorepo) so it shares that code and one build;
Railway runs it as its **own service** with a different start command.

It is the bot's **only** backend gateway: the bot calls `/api/*` for every
domain operation and touches neither `services`/`stores` nor the database.

## Layout

```
api/
  main.py            # app factory (create_app), lifespan, global error handler
  deps.py            # require_internal_token (shared-secret guard)
  schemas.py         # pydantic request/response models (edge validation)
  routers/
    system.py        # GET /  ·  GET /health  ·  GET /health/db      (open)
    internal.py      # GET /api/ping                             (token-guarded)
    users.py         # POST /api/users/resolve · GET /api/users/settings
                     #   · POST /api/users/timezone · POST /api/users/language
    notes.py         # POST /api/notes (capture) · POST /api/notes/voice
                     #   · POST /api/notes/{id}/enrich · POST /api/notes/{id}/path
                     #   · GET  /api/notes/paths · GET /api/notes/{id}/link-candidates
                     #   · POST /api/notes/{from}/links/{to}/toggle
    reminders.py     # GET /api/reminders · GET /api/reminders/count
                     #   · POST /api/reminders/claim-due
                     #   · POST /api/reminders/{id}/{cancel,done,snooze,retry}
    search.py        # POST /api/search
```

All `/api/*` routes are token-guarded. The bot-side caller is
`api_client.ApiClient` (async httpx); its method names mirror these endpoints.

The API is the **single gateway** for a thin client: the client never touches the
database. Because the domain keys on an internal `user_id` (not on any client's
identity), a client first exchanges its external identity for a `user_id`, then
calls the domain endpoints with it.

Bot flow:

```
chat_id ──POST /api/users/resolve──▶ user_id      (cached per chat)
user_id ──GET  /api/users/settings──▶ tz / locale / active reminders
user_id + text ──POST /api/notes──▶ note_id (+ reminder if time-bearing)
user_id + query ──POST /api/search──▶ answer
```

- `POST /api/users/resolve` — `{chat_id}` → `{user_id}` (creates on first
  sight). `chat_id` is the only Telegram-specific field in the whole API; every
  other endpoint is client-agnostic.
- `POST /api/search` — `{user_id, query}` → `{answer}`; the agenda-aware RAG
  call (`search_service.answer`). Per-user attributes (timezone, language) are
  resolved **server-side** from `user_id` (`user_service.settings`).

The bot is fully cut over: `api_client.ApiClient` (async httpx, wired to
`API_BASE_URL` / `API_INTERNAL_TOKEN`) is the bot's sole path to the backend, and
its method names mirror the `/api/*` endpoints. The `chat_id → user_id`
mapping is stable, so the bot caches it to avoid a resolve round-trip per update.

Reminder delivery stays in the bot (it owns the Telegram transport): the
dispatcher calls `POST /api/reminders/claim-due` to atomically claim due
rows, sends each message, then calls `.../{id}/done` on success or
`.../{id}/retry` to hand a failed send back for the next poll.

## Section boundary: strict pure mappers

For read endpoints that load rows and shape a response, keep orchestration in
the section's `endpoints.py` and make the shaping function in `helper.py` a
strict pure mapper. The mapper must receive every value it needs as an argument
and return a value determined only by those arguments.

A strict pure mapper must not:

- import or call the section's `db` module;
- read the clock, generate randomness, sign tokens, or call external services;
- mutate its arguments or shared state;
- hide additional queries inside loops or nested helper functions.

The endpoint is the impure boundary. It resolves authentication, performs DB
queries, calls clock-/secret-/network-dependent functions, and passes their
results into the mapper. Keep bulk loading at this boundary to avoid N+1
queries. When one query depends on another result, make that dependency visible
in the endpoint: load primary rows, derive IDs, then bulk-load related rows.

The feed section is the reference implementation:

```python
def feed(user_id: int = Depends(current_user)) -> list[FeedCard]:
  notes = db.list_notes(user_id)
  edges = db.all_links(user_id)
  linked_note_ids = {note_id for edge in edges for note_id in edge}
  briefs = db.notes_brief(user_id, linked_note_ids)
  attachment_rows = db.attachments_for_notes([note["id"] for note in notes])
  attachments = {
    note_id: helper.attachment_views(rows)
    for note_id, rows in attachment_rows.items()
  }
  return [
    FeedCard(**item)
    for item in helper.feed_for_user(notes, edges, briefs, attachments)
  ]
```

Here `attachment_views` is intentionally called before `feed_for_user` because
URL signing reads the current time and a secret. `feed_for_user` itself only
maps the supplied notes, links, briefs, and already-signed attachment views.
Calling it twice with equivalent inputs therefore produces equivalent output.

Use this sequence when purifying another read endpoint:

1. List every DB query and non-deterministic dependency used by the helper.
2. Move those operations to `endpoints.py`, preserving authorization and bulk
   query behavior.
3. Pass loaded rows and precomputed values explicitly to the mapper.
4. Remove the helper's `db` import and user ID if they are no longer needed.
5. Test the mapper with plain in-memory inputs, including empty and missing
   related-data cases; separately test endpoint orchestration with mocked DB
   calls.

Do not force write workflows, transactions, or agent execution into this
pattern. Those helpers coordinate domain effects by design. Apply strict
purification to functions whose responsibility is response shaping,
normalization, filtering, grouping, or other deterministic transformation.

## Run locally

```bash
uvicorn api.main:app --reload --port 8080
curl localhost:8080/health          # {"status":"ok"}
```

## Run on Railway

Three services in one project (shared repo, shared private network): **API**,
**bot**, and the **webapp** static host. Each is created from this same repo
(New → GitHub Repo → this repo) and selects its Dockerfile via a
`RAILWAY_DOCKERFILE_PATH` service variable — there are no `railway.*.json`
config-as-code files (Railway deprecated Config-as-Code; configure services in
the dashboard, or with `.railway/railway.ts` IaC).

1. **Push the repo.**
2. **API service:** set `RAILWAY_DOCKERFILE_PATH=Dockerfile.api`. Start command
   is the image's `CMD` (`python -m api.run` — a dual-stack launcher, see the
   note below). Env: `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `OPENAI_API_KEY`,
   `PORT=8080` (stable internal port), `API_INTERNAL_TOKEN=<random secret>`,
   `WEBAPP_ALLOWED_ORIGINS=<webapp public origin>` (CORS).
3. **Bot service:** set `RAILWAY_DOCKERFILE_PATH=Dockerfile.bot`. Env: same
   `API_INTERNAL_TOKEN`, `API_BASE_URL=http://${{<ApiServiceName>.RAILWAY_PRIVATE_DOMAIN}}:8080`,
   and `WEBAPP_URL=<webapp public origin>` (Menu Button).
4. **Webapp service:** set `RAILWAY_DOCKERFILE_PATH=Dockerfile.webapp` and
   `VITE_API_BASE=<API public origin>` (baked into the build). Generate a public
   domain for it; that domain is the Mini App URL (BotFather + `WEBAPP_URL`).
5. **Keep the API private:** do *not* generate a public domain for it unless the
   webapp needs it — the bot reaches it at `http://<api>.railway.internal:8080`.
   (The webapp is a browser client, so its `VITE_API_BASE` does need a public API
   origin; give the API a public domain if you host the webapp separately.)

### Startup ordering (important)

**The API owns migrations, so on a fresh database it must start before the bot.**
The bot no longer migrates and assumes the schema exists; if it starts first
against an empty database, its DB calls fail until the API has migrated.

- Preferred: make the bot **wait for** the API. On Railway, add a *Reference*
  from the bot service to the API (Settings → Deploy → *Wait for service*, or a
  service dependency), so the bot deploys only after the API is healthy (the API
  reports healthy only after `/health` passes, which is after migrations run).
- Alternative: run migrations as a one-off **pre-deploy** step (`python
  migrate.py`) shared by the project, then neither service depends on the other's
  start order.

Once the bot is fully cut over to call the API (no direct DB access), this
ordering stops mattering — only the API touches the database.

> ### Binding: dual stack (`python -m api.run`)
>
> Railway **private** networking is IPv6-only, so the app must listen on `::`
> (a plain `0.0.0.0` bind is unreachable privately — the bot couldn't call it).
> But Railway's **public** edge reaches the container over **IPv4**, and a plain
> `--host ::` socket is IPv6-only, so it refuses those connections — the public
> domain returns **502** even though the app is up and private calls work.
>
> `api/run.py` fixes both at once: it binds `::` with `IPV6_V6ONLY=0`, a single
> dual-stack socket that accepts IPv6 (private) **and** IPv4-mapped (public) and
> hands it to uvicorn. That's why the start command is `python -m api.run` rather
> than `uvicorn … --host ::`.

## Access model

- **No public domain.** The service is reachable only on the project's private
  network. That network is the primary access control.
- **`API_INTERNAL_TOKEN`** is defence in depth: if set, `/api/*` requires a
  matching `X-Internal-Token` header. `/health` stays open (no token) for manual
  checks and for the bot's `ApiClient.health()`.
- **No Railway deploy healthcheck.** No `healthcheckPath` is configured;
  Railway marks the deploy healthy once the process stays up. `/health` still
  exists for on-demand checks. (The dual-stack `api/run.py` bind — see above —
  means both the public edge and any IPv4 probe can now reach the app, but the
  healthcheck stays off to keep deploys simple.)
- **The API owns schema migrations.** As the backend gateway it runs
  `run_migrations()` on startup (lifespan) before serving requests; client
  adapters (the bot) no longer migrate and assume the schema is present.
