"""
API service entrypoint (empty scaffold).

Runs as its own Railway service on the project's private network. The Telegram
bot (and future web/iOS clients) will call it over
`http://<service>.railway.internal:<port>`. It is intended to have **no public
domain** — the private network is the primary access control, with an optional
shared token (`API_INTERNAL_TOKEN`) as defence in depth.

Local:    uvicorn api.main:app --reload --port 8080
Railway:  uvicorn api.main:app --host :: --port $PORT
          (bind to `::` — Railway private networking is IPv6-only)
"""

import pathlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import config
from migrate import run_migrations
from api.routers import system, internal, users, notes, reminders, search, chat

# The Telegram Mini App (static single-page) lives in the repo; the API serves it
# so it shares the API's public domain (same origin → no CORS for /api/*).
WEBAPP_DIR = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "Telegram_WebApp"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class NoCacheStaticFiles(StaticFiles):
    """Serve the Mini App with `Cache-Control: no-cache` so clients (Telegram
    webview / browsers) always revalidate against the server. StaticFiles still
    sends ETag/Last-Modified, so unchanged files return a cheap 304 while a new
    deploy is picked up immediately — no manual reload."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The API service owns schema migrations: it is the backend gateway, so it
    # brings the database up to date on startup before serving any client.
    logger.info("API starting: %s v%s", config.API_TITLE, config.API_VERSION)
    run_migrations()
    yield
    logger.info("API shutting down")


def create_app() -> FastAPI:
    """Application factory — keeps construction testable and import-side-effect free."""
    app = FastAPI(
        title=config.API_TITLE,
        version=config.API_VERSION,
        lifespan=lifespan,
        # Docs are off by default; enable with API_DOCS_ENABLED=true for debugging.
        docs_url="/docs" if config.API_DOCS_ENABLED else None,
        redoc_url=None,
        openapi_url="/openapi.json" if config.API_DOCS_ENABLED else None,
    )

    # Public Mini App endpoints are called cross-origin from the user's browser,
    # so they need CORS. They authenticate per-request via signed initData, not
    # cookies, so a wildcard origin is safe (no credentials).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.WEBAPP_ALLOWED_ORIGINS,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(system.router)
    app.include_router(internal.router)
    app.include_router(users.router)
    app.include_router(notes.router)
    app.include_router(reminders.router)
    app.include_router(search.router)
    app.include_router(chat.router)

    # Serve the Mini App at /app/ (index.html). Same origin as /api/notes.
    if WEBAPP_DIR.is_dir():
        app.mount("/app", NoCacheStaticFiles(directory=str(WEBAPP_DIR), html=True), name="webapp_static")
        logger.info("Serving web app from %s at /app/", WEBAPP_DIR)
    else:
        logger.warning("Web app directory not found: %s", WEBAPP_DIR)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Global safety net: log with context, never leak internals to the caller.
        logger.exception("Unhandled API error: %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal_error"})

    return app


app = create_app()
