"""
System endpoints: liveness + readiness.

Unauthenticated on purpose — Railway's healthcheck hits `/health` over the
private network during every deploy, and it must stay cheap and dependency-free.
"""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])


@router.get("/")
def root():
    return {"service": "daily-notes-api", "status": "ok"}


@router.get("/health")
def health():
    """Liveness — fast, no external calls. Used by the Railway healthcheck."""
    return {"status": "ok"}


@router.get("/health/db")
def health_db():
    """Readiness — verifies the database is reachable."""
    try:
        with db.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return {"status": "ok", "db": "up"}
    except Exception:
        logger.exception("DB health check failed")
        return JSONResponse(status_code=503, content={"status": "degraded", "db": "down"})
