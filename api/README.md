# API service

A separate, independently deployable service that fronts the same domain layer
the Telegram bot uses (`note_service`, `search_service`, `reminders`, `links`,
…). It lives in this one repo (monorepo) so it shares that code and one build;
Railway runs it as its **own service** with a different start command.

Right now it is an **empty scaffold**: only health/system endpoints plus a
private, token-guarded `/internal` namespace where the bot's calls will migrate.

## Layout

```
api/
  main.py            # app factory (create_app), lifespan, global error handler
  deps.py            # require_internal_token (shared-secret guard)
  schemas.py         # pydantic request/response models (edge validation)
  routers/
    system.py        # GET /  ·  GET /health  ·  GET /health/db      (open)
    internal.py      # GET /internal/ping                             (token-guarded)
    users.py         # POST /internal/users/resolve                   (token-guarded)
    search.py        # POST /internal/search                          (token-guarded)
```

The API is the **single gateway** for a thin client: the client never touches the
database. Because the domain keys on an internal `user_id` (not on any client's
identity), a client first exchanges its external identity for a `user_id`, then
calls the domain endpoints with it.

Intended bot flow (once cut over):

```
chat_id ──POST /internal/users/resolve──▶ user_id      (cache it per session)
user_id + query ──POST /internal/search──▶ answer
```

- `POST /internal/users/resolve` — `{chat_id}` → `{user_id}` (creates on first
  sight). `chat_id` is the only Telegram-specific field in the whole API; every
  other endpoint is client-agnostic.
- `POST /internal/search` — `{user_id, query}` → `{answer}`; the same agenda-aware
  RAG call the bot makes in-process today (`search_service.answer`). The client
  sends only `user_id` and `query`; per-user attributes (timezone, language) are
  resolved **server-side** from `user_id` (`user_service.settings`).

The bot is unchanged for now; `ApiClient.resolve_user(...)` / `ApiClient.search(...)`
are the seams for cutting it over later. The `chat_id → user_id` mapping is stable,
so the client should cache it to avoid a resolve round-trip on every message.

The bot-side caller lives at the repo root in `api_client.py` (async httpx),
wired to `API_BASE_URL` / `API_INTERNAL_TOKEN`. It is **not** used by the bot
handlers yet — the seam exists so switching a handler to call the API later is a
one-line swap.

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
   `uvicorn api.main:app --host :: --port $PORT`). Point the bot service at
   `railway.bot.json`.
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

> Private networking is **IPv6-only**, so the `--host ::` bind is required
> (`0.0.0.0` is not reachable internally).

## Access model

- **No public domain.** The service is reachable only on the project's private
  network. That network is the primary access control.
- **`API_INTERNAL_TOKEN`** is defence in depth: if set, `/internal/*` requires a
  matching `X-Internal-Token` header. `/health` stays open (no token) for manual
  checks and for the bot's `ApiClient.health()`.
- **No Railway deploy healthcheck.** The service binds IPv6-only (`::`) for
  private networking, and Railway's healthcheck probe can arrive over IPv4 and be
  rejected — failing the deploy even though the app is up. So `railway.api.json`
  has no `healthcheckPath`; Railway marks the deploy healthy once the process
  stays up. `/health` still exists for on-demand checks.
- **The API owns schema migrations.** As the backend gateway it runs
  `run_migrations()` on startup (lifespan) before serving requests; client
  adapters (the bot) no longer migrate and assume the schema is present.
