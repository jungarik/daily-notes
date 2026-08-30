# Mini App (React + Vite)

The Telegram Mini App: a React + Vite SPA, one component per section (Header,
Dock, Feed, Browser, MapView, Search, Chat, NoteSheet, ContextMenu,
FolderFilter) over a small `AppContext` store, with a single reused `styles.css`.
It is deployed as its own static host and calls the API cross-origin.

## Layout

```
src/
  main.jsx            # entry: initTelegram() + <AppProvider><App/></AppProvider>
  App.jsx             # shell: Header + views (Feed/Map/Browser/Search/Chat) + Dock + overlays
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
