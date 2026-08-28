# Telegram Web App — note browser

A Telegram Mini App (a web page opened from inside Telegram) that browses your
notes as an Obsidian-style vault: PARA folders on top, notes shown as
`title.md` files. Dark theme, monospace/"console" font.

It's a **client adapter**, like `frontend/Telegram_Bot/` — it renders the same
notes the bot captures. This first version is the **browser**; the note card
(open a note) and the mind-map graph come next.

## Files

- `index.html` — the whole app (self-contained: HTML + CSS + vanilla JS, no build
  step). Loads Telegram's `telegram-web-app.js` for expand/theme/auth and works
  standalone in a plain browser too (falls back to sample data).

## Run / preview locally

Just open `index.html` in a browser — it renders with built-in sample notes.
(In a plain browser the Telegram SDK is absent; the app handles that gracefully.)

## Deploy

Telegram Mini Apps must be served over **HTTPS from a public URL**. Host the
folder on any static host (GitHub Pages, Cloudflare Pages, Netlify, a Railway
static service, etc.) and note the resulting `https://…/index.html` URL.

## Wire it to the bot

Set `WEBAPP_URL` on the **bot** service to the deployed URL. On startup the bot
sets a Menu Button (the button next to the message input) that opens the app:

```
WEBAPP_URL=https://your-host/telegram-webapp/
```

Leave it unset and the button simply stays off (the bot logs that it's disabled).

## Making it show real notes

The backend endpoint now exists: **`GET /api/notes`** (public, in
the `/api/notes*` routes) returns the caller's notes as
`[{ "id": int, "title": str, "path": str|null }]` (title falls back to a text
snippet for notes not yet enriched). It authenticates with Telegram **initData**
— the app sends it in the `X-Telegram-Init-Data` header, and the API verifies the
HMAC against `BOT_TOKEN` (`api/telegram_auth.py`), resolves the Telegram user →
internal `user_id`, and returns only that user's notes. The tree is built purely
from each note's `path` (PARA root + at most one sub-folder).

To go live:

1. **Give the API a public URL.** The API service has no public domain by default
   (private network only). Generate one (e.g. a Railway public domain) so the
   browser can reach `/api/*`. `/api/* (token-guarded)` stays token-guarded and `/health`
   stays open, so exposing the app is safe.
2. **Set `BOT_TOKEN` on the API service** (same token as the bot) — it's needed to
   verify initData. Optionally set `WEBAPP_INITDATA_MAX_AGE_SECONDS` (default
   86400) and `WEBAPP_ALLOWED_ORIGINS` (default `*`).
3. **Point the app at the API:** set `window.__API_BASE__` to the API's public
   base URL — inject a tiny `<script>window.__API_BASE__="https://your-api"</script>`
   before `index.html`'s main script at deploy time, or hardcode it. The app
   already calls `{API_BASE}/api/notes` with the initData header and falls back
   to sample data on any error.

## Roadmap

- Note card: tap a `.md` file to open its content (currently a stub sheet).
- Mind-map graph: visualize `note_links` (the Zettelkasten graph).
