# Mini App (React + Vite)

The Telegram Mini App: a React + Vite SPA, one component per section (Header,
Dock, Feed, Explorer, MapView, Search, Chat, NoteSheet, ContextMenu,
FolderFilter) over a small `AppContext` store, with a single reused `styles.css`.
It is deployed as its own static host and calls the API cross-origin.

The **change-path sheet** is two stacked comboboxes: the root folder over the
sub-folder. The root field lists the fixed roots (`GET /api/contextmenu/roots`)
and is read-only; the sub-folder field lists what exists under the chosen root
(`GET /api/contextmenu/children?root=`), narrows as you type, and accepts a new
name. Choosing a different root clears the sub-folder, and an empty sub-folder
means the root itself. Notes are two levels deep (saving truncates anything
deeper). A folder only moves between roots, so its sheet is the root field
alone and the rest of its path travels with it.

The feed/preview card (`NoteCard.jsx`) leads with the note's own text (images
above it), then date + `⋮`, path, tags and linked-note chips. Text over 100
characters is clamped with an inline "… more" / "less" (`lib/format.clampText`);
the linked-note row has no heading and renders nothing when empty. The bottom
sheet's grip is sticky and spans the sheet's padding, so it stays visible while
a tall card scrolls. It renders **no title** — the date row, path,
tags, text and linked notes only.

**Nothing in the app shows `notes.title` except the map.** `feed`, `explorer`,
`notesheet` and `search` label a note with the first 60 characters of its own
text and send it as `label` (not `title`); the client reads `label` everywhere
and has no `|| "untitled"` fallbacks left, since the server never sends an
empty one. `mapview` keeps `title` because its cards are too small for an
opening sentence, and `NoteMiniCard` accepts either key because it serves both.
The explorer's rows now sort by that label.

The note context menu offers **Edit** above **Path** (notes only); its items
use the app's inline-SVG glyphs, not emoji. Edit opens the Add Note overlay
with `note_id` and immediately focuses its textarea to open the mobile
keyboard; the overlay then reads the note from `GET /api/addnote/{id}`
(`{id, text, path, tags, attachments, linked_note_ids}` — the extra fields are
held in state for the still-disabled side buttons) and fills the field — showing a "Loading…" placeholder meanwhile, never
overwriting text typed in the gap, and leaving the page open with an inline
message if the read fails. The header's plus opens it with no note ID and an
empty field, and closing clears the ID. Saving works: ✓ calls `POST /api/addnote`
(new) or `PUT /api/addnote/{id}` (edit) with `{text, path, tags}`, then closes
and `reload()`s the vault. The tick is dimmed while saving and while the text
is empty; a failure keeps the page open with an inline message. ✕ still
discards. `tags` is sent empty until its editor exists.

The page's folder is two buttons over one saved `path` string. **Path** (root
folder) and **sub-folder** (the level below it, a `/..` icon) each open
`PathWheel.jsx`, a panel-less drum anchored to its button — raised plain-text pill
rows that bow along a circle and fade with it
(`lib/format.wheelItem`). The root wheel is fed by `GET /api/addnote/roots`
(root folders + `default_root`) and lists only those; the sub-folder wheel by
`GET /api/addnote/children?root=` (distinct second-level names already in use,
filtered in SQL) and is disabled until a root is chosen. Only the sub-folder wheel has a
filter row (row 0), which also accepts a new name (slashes are dropped as
typed); the root wheel has none. Picking a different root clears the sub-folder; saving is
unchanged (`path` = `""` | `Root` | `Root/child`). Long labels clip on the
left (`direction: rtl` + `<bdi>`), keeping the leaf. A chosen folder turns the
button's ring and glyph blue — not its fill. `tags` (a `#` icon) is still disabled; the
`link` button is gone.

## Layout

```
src/
  main.jsx            # entry: initTelegram() + <AppProvider><App/></AppProvider>
  App.jsx             # shell: Header + views (Feed/Map/Explorer/Search/Chat) + Dock + overlays
  styles.css          # app styles
  lib/
    telegram.js       # tg init + INIT_DATA
    api.js            # API_BASE + fetch helpers (all /api/* endpoints)
    format.js         # fmtDate, notePathKey, dateText, tagsText, linkedItems
  store/AppContext.jsx# global state (view/filter/sheet/chat) + actions; boot fetch
  components/*.jsx    # one per UI section
  graph/*             # imperative canvas graph engine (used by MapView)
```

## Build

```
npm --prefix browser/webapp install
npm --prefix browser/webapp run build     # → browser/webapp/dist
```

`vite.config.js` sets `base: "/"` (served at the host root). `VITE_API_BASE` is
baked into the build and must point at the API's public origin.

## Hosting on Railway (separate static service)

The app is a standalone Railway service built from `Dockerfile.webapp` (Vite
build → Caddy static server). The API (`Dockerfile.api`) is a pure `/api` gateway
and serves no frontend. There are no `railway.*.json` config files — each service
selects its Dockerfile via a `RAILWAY_DOCKERFILE_PATH` variable in the dashboard.
To deploy:

1. On the **webapp** service set `RAILWAY_DOCKERFILE_PATH=Dockerfile.webapp` and
   `VITE_API_BASE` = the API's public origin (baked into the build at
   `Dockerfile.webapp`'s `ARG VITE_API_BASE`).
2. On the **API** service add the webapp's public origin to
   `WEBAPP_ALLOWED_ORIGINS` (CORS; `*` also works since auth is header-based via
   signed initData).
3. Point BotFather's Mini App URL (and `WEBAPP_URL` on the bot) at the webapp
   service's domain.

The client's `API_BASE` reads `VITE_API_BASE` → `window.__API_BASE__` →
`location.origin`, so local dev without `VITE_API_BASE` falls back to the page
origin (set `window.__API_BASE__` to a deployed API when running outside
Telegram).

## Dev

```
npm --prefix browser/webapp run dev
```
Set `window.__API_BASE__` to your deployed API origin when running outside
Telegram, since initData/auth comes from the API.
