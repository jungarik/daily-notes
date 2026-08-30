# Plugin capture via Personal Access Tokens

**Status:** proposed (implementation spec)
**Goal:** let headless, per-user clients — a Chrome extension, a Codex/Claude MCP
tool, etc. — quickly capture snippets into the vault, without weakening the
existing auth model.

## Motivation

Codex, Claude, and a Chrome extension are the same shape: **headless, per-user
clients that push a snippet into the vault.** So we don't build three
integrations — we build one capability (a public capture endpoint + a per-user
credential), and each plugin becomes a thin client on top of it.

This also advances the multi-client architecture already in place: clients stay
thin, the API stays the single gateway, and every request derives `user_id` from
a *verified credential* rather than a client-supplied parameter.

## Where this fits in the current auth model

The API already authenticates two surfaces, and this adds a third credential
type:

| Surface        | Credential                         | `user_id` source            |
|----------------|------------------------------------|-----------------------------|
| `/internal/*`  | shared `API_INTERNAL_TOKEN` + private net | trusted param (the bot)     |
| `/webapp/*`    | Telegram `initData` (HMAC)         | derived from verified initData |
| **`/capture`** *(new)* | **Personal Access Token (Bearer)** | **derived from the token**  |

`/internal/*` (bot) and `/webapp/*` (Mini App) are unchanged. The new public
surface never trusts a client-supplied `user_id`.

## Data model — `migrations/00NN_access_tokens.sql`

Append-only migration adding:

```
access_tokens (
  id           bigserial primary key,
  user_id      bigint not null references users(id),
  token_hash   text   not null unique,   -- sha256(pepper + raw); raw never stored
  prefix       text   not null,          -- first ~10 chars, for display + lookup
  label        text,                      -- e.g. "Chrome", "Codex"
  scopes       text[] not null default '{capture}',
  created_at   timestamptz not null default now(),
  last_used_at timestamptz,
  revoked_at   timestamptz               -- null = active
)
```

Indexes: unique on `token_hash`, plain on `user_id`.

## Persistence — `stores/token_store.py`

Thin SQL only:

- `create(user_id, token_hash, prefix, label, scopes) -> row`
- `get_active_by_hash(token_hash) -> row | None`  (ignores revoked)
- `list_by_user(user_id) -> [row]`
- `touch_last_used(id) -> None`
- `revoke(user_id, token_id) -> bool`  (ownership-checked)

## Domain — `services/token_service.py`

- `generate()` → high-entropy token, `secrets.token_urlsafe(32)`, formatted
  `dn_pat_<random>`; keep the first ~10 chars as `prefix`.
- `_hash(raw)` → `sha256(config.TOKEN_PEPPER + raw)`. (The token is already
  256-bit, so the hash is safe; the pepper is defense-in-depth against a DB leak.)
- `create(user_id, label, scopes=("capture",)) -> (raw_token, row)` — returns the
  **raw token once**; only the hash is persisted.
- `verify(raw) -> (user_id, scopes) | None` — hash → `get_active_by_hash` →
  constant-time compare → `touch_last_used`.
- `list(user_id)`, `revoke(user_id, token_id)`.

## Auth dependency — `api/deps.py`

Add a dependency factory:

```
require_access_token(scope: str) -> Depends
```

Reads `Authorization: Bearer dn_pat_…`, calls `token_service.verify`, checks the
required scope is present, and **returns the `user_id`**. Raises `401` on
missing/invalid/revoked, `403` on missing scope. Public endpoints depend on this
and never accept a `user_id` parameter.

## Public capture — `api/routers/capture.py` (new, no `/internal` prefix)

```
POST /capture        (Authorization: Bearer <PAT>, scope "capture")
  body: { text: str, source?: str, url?: str }
  -> { note_id: int }
```

- `user_id` comes from the dependency, not the body.
- Validates/bounds `text` length (`CAPTURE_MAX_CHARS`).
- Calls the **same** `note_service.capture_note(user_id, text)` the bot uses, so
  captures flow through enrichment / reminders / search identically.
- Records `source` (`chrome` / `codex` / `claude`) and `url` for provenance.
- CORS enabled for this route (browser extensions make cross-origin requests).
- Per-token rate limit.

## Token management — `/internal/tokens` (bot-driven, internal-token-guarded)

New router (or extend `users.py`). Because the bot mints tokens on the user's
behalf, these stay on the trusted internal surface with `user_id`:

- `POST /internal/tokens { user_id, label, scopes? }`
  → `{ token, id, prefix, label, scopes }`  (raw token returned **once**)
- `GET /internal/tokens?user_id=`
  → `[ { id, label, prefix, scopes, created_at, last_used_at } ]`  (no raw token)
- `POST /internal/tokens/{id}/revoke { user_id }` → `{ ok }`  (ownership-checked)

New Pydantic models in `api/schemas.py`.

## Bot commands — `capture/Telegram_Bot/`

- `api_client.py`: add `create_token`, `list_tokens`, `revoke_token`.
- Commands:
  - `/token <label>` — mint a token; reply with it + a "paste this into the
    plugin; it won't be shown again" note.
  - `/tokens` — list tokens with inline **revoke** buttons.
- Add en/uk locale strings; register in the command menu.

## Config & guardrails — `config.py` / `.env.example`

- `TOKEN_PEPPER` (secret), `TOKEN_PREFIX=dn_pat_`.
- `CAPTURE_MAX_CHARS`, `CAPTURE_RATE_PER_MIN`.
- Guardrails: bound text size; rate-limit per token; log token use by **id +
  prefix only** (never the raw token); constant-time compare; HTTPS-only public
  edge (already the case).

## Verification (stubbed, no DB)

- `token_service`: generate → verify round-trip; wrong/revoked token → `None`;
  scope enforcement.
- Dependency: returns `user_id` for a valid token; `401`/`403` otherwise.
- `/capture`: calls `note_service.capture_note` with the derived `user_id`;
  rejects oversized text.
- Token management: create returns raw once; list omits the raw token; revoke is
  ownership-checked.
- `compileall` the tree.

## Sequencing

1. Migration + `token_store`
2. `token_service`
3. `require_access_token` dependency
4. `/capture` router + schemas
5. `/internal/tokens` management + schemas
6. bot `api_client` + `/token` / `/tokens` commands + locales
7. config / CORS / rate limit
8. verify

Each step is independently testable.

## After the core (separate, thin clients)

- **Chrome extension** — context-menu "Capture to vault" + popup; POSTs the
  selection + page URL to `/capture` with the pasted token.
- **Claude / Codex** — a small **MCP server** exposing a `capture_note` tool that
  POSTs to `/capture`; usable from Claude, Codex, and Cowork. Optional Claude
  *skill* wrapper.

## Open decision

`source` / `url` provenance: a small **new column** on `notes` (clean, queryable
— "show everything I clipped from Chrome") vs folding into tags/text for now.
Recommendation: a `source` column, since origin-based queries will be wanted.
