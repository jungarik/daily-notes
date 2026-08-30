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

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import config
from migrate import run_migrations
from api.routers import system, internal, users, notes, reminders, search, chat
# Section verticals (each: endpoints.py → helper.py → store.py). Being migrated
# off the shared services/stores routers above, one section at a time.
from api.feed.endpoints import router as feed_router
from api.notecard.endpoints import router as notecard_router
from api.browser.endpoints import router as browser_router
from api.notesheet.endpoints import router as notesheet_router
from api.mapview.endpoints import router as mapview_router
from api.contextmenu.endpoints import router as contextmenu_router
from api.header.endpoints import router as header_router
from api.search.endpoints import router as search_section_router

# The Telegram Mini App (browser/webapp, React) is deployed as its own static
# host (see Dockerfile.webapp) and calls this API cross-origin, so the API is a
# pure /api gateway and serves no client itself.

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


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

    # The Mini App is a separate static host that calls /api cross-origin, so
    # CORS is required. Endpoints authenticate per-request via signed initData,
    # not cookies, so a wildcard origin is safe (no credentials). In production,
    # set WEBAPP_ALLOWED_ORIGINS to the Mini App's origin to be explicit.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.WEBAPP_ALLOWED_ORIGINS,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(system.router)
    app.include_router(internal.router)
    app.include_router(users.router)
    app.include_router(notes.router)
    app.include_router(reminders.router)
    app.include_router(search.router)
    app.include_router(chat.router)

    # Section verticals (new /api/<section> surfaces).
    app.include_router(feed_router)
    app.include_router(notecard_router)
    app.include_router(browser_router)
    app.include_router(notesheet_router)
    app.include_router(mapview_router)
    app.include_router(contextmenu_router)
    app.include_router(header_router)
    app.include_router(search_section_router)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Global safety net: log with context, never leak internals to the caller.
        logger.exception("Unhandled API error: %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal_error"})

    return app


app = create_app()
