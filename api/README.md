# API service

A separate, independently deployable service that fronts the same domain layer
the Telegram bot uses (`note_service`, `search_service`, `reminders`, `links`,
…). It lives in this one repo (monorepo) so it shares that code and one build;
Railway runs it as its **own service** with a different start command.

It is the bot's **only** backend gateway: the bot calls `/internal/*` for every
domain operation and touches neither `services`/`stores` nor the database.

## Layout

```
api/
  main.py            # app factory (create_app), lifespan, global error handler
  deps.py            # require_internal_token (shared-secret guard)
  schemas.py         # pydantic request/response models (edge validation)
  routers/
    system.py        # GET /  ·  GET /health  ·  GET /health/db      (open)
    internal.py      # GET /internal/ping                             (token-guarded)
    users.py         # POST /internal/users/resolve · GET /internal/users/settings
                     #   · POST /internal/users/timezone · POST /internal/users/language
    notes.py         # POST /internal/notes (capture) · POST /internal/notes/voice
                     #   · POST /internal/notes/{id}/enrich · POST /internal/notes/{id}/path
                     #   · GET  /internal/notes/paths · GET /internal/notes/{id}/link-candidates
                     #   · POST /internal/notes/{from}/links/{to}/toggle
    reminders.py     # GET /internal/reminders · GET /internal/reminders/count
                     #   · POST /internal/reminders/claim-due
                     #   · POST /internal/reminders/{id}/{cancel,done,snooze,retry}
    search.py        # POST /internal/search
```

All `/internal/*` routes are token-guarded. The bot-side caller is
`api_client.ApiClient` (async httpx); its method names mirror these endpoints.

The API is the **single gateway** for a thin client: the client never touches the
database. Because the domain keys on an internal `user_id` (not on any client's
identity), a client first exchanges its external identity for a `user_id`, then
calls the domain endpoints with it.

Bot flow:

```
chat_id ──POST /internal/users/resolve──▶ user_id      (cached per chat)
user_id ──GET  /internal/users/settings──▶ tz / locale / active reminders
user_id + text ──POST /internal/notes──▶ note_id (+ reminder if time-bearing)
user_id + query ──POST /internal/search──▶ answer
```

- `POST /internal/users/resolve` — `{chat_id}` → `{user_id}` (creates on first
  sight). `chat_id` is the only Telegram-specific field in the whole API; every
  other endpoint is client-agnostic.
- `POST /internal/search` — `{user_id, query}` → `{answer}`; the agenda-aware RAG
  call (`search_service.answer`). Per-user attributes (timezone, language) are
  resolved **server-side** from `user_id` (`user_service.settings`).

The bot is fully cut over: `api_client.ApiClient` (async httpx, wired to
`API_BASE_URL` / `API_INTERNAL_TOKEN`) is the bot's sole path to the backend, and
its method names mirror the `/internal/*` endpoints. The `chat_id → user_id`
mapping is stable, so the bot caches it to avoid a resolve round-trip per update.

Reminder delivery stays in the bot (it owns the Telegram transport): the
dispatcher calls `POST /internal/reminders/claim-due` to atomically claim due
rows, sends each message, then calls `.../{id}/done` on success or
`.../{id}/retry` to hand a failed send back for the next poll.

## Run locally

```bash
uvicorn api.main:app --reload --port 8080
curl localhost:8080/health          # {"status":"ok"}
```

## Run on Railway

Two services in one project (shared repo, shared private network):

1. **Push the repo.** Both services build from the same image.
2. **Create the API service** in the same project (New → GitHub Repo → this repo).
   Point Settings → *Config-as-code* at `railway.api.json` (start command
   `python -m api.run` — a dual-stack launcher, see the note below). Point the bot
   service at `railway.bot.json`.
3. **API env:** `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `OPENAI_API_KEY`,
   `PORT=8080` (stable internal port), `API_INTERNAL_TOKEN=<random secret>`.
4. **Bot env:** same `API_INTERNAL_TOKEN`, and
   `API_BASE_URL=http://${{<ApiServiceName>.RAILWAY_PRIVATE_DOMAIN}}:8080`.
5. **Keep the API private:** do *not* generate a public domain — the private
   network is the access control. The bot reaches it at
   `http://<api>.railway.internal:8080`.

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
- **`API_INTERNAL_TOKEN`** is defence in depth: if set, `/internal/*` requires a
  matching `X-Internal-Token` header. `/health` stays open (no token) for manual
  checks and for the bot's `ApiClient.health()`.
- **No Railway deploy healthcheck.** `railway.api.json` has no `healthcheckPath`;
  Railway marks the deploy healthy once the process stays up. `/health` still
  exists for on-demand checks. (The dual-stack `api/run.py` bind — see above —
  means both the public edge and any IPv4 probe can now reach the app, but the
  healthcheck stays off to keep deploys simple.)
- **The API owns schema migrations.** As the backend gateway it runs
  `run_migrations()` on startup (lifespan) before serving requests; client
  adapters (the bot) no longer migrate and assume the schema is present.
