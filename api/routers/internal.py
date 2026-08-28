"""Connectivity ping — token-guarded, for a client to verify it can reach and
authenticate against the API (used by the bot at startup)."""

from fastapi import APIRouter, Depends

from api.deps import require_internal_token

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/ping", dependencies=[Depends(require_internal_token)])
def ping():
    return {"pong": True}
