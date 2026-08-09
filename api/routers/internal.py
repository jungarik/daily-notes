"""
Internal endpoints — reachable only inside Railway's private network and, when
`API_INTERNAL_TOKEN` is set, additionally guarded by a shared token.

This is the namespace the bot's calls will migrate into (capture, enrich,
search, links, ...). It's intentionally empty for now apart from a ping the
clients can use to verify connectivity.
"""

from fastapi import APIRouter, Depends

from api.deps import require_internal_token

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_token)],
)


@router.get("/ping")
def ping():
    return {"pong": True}
