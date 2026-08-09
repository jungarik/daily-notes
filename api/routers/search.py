"""
Search endpoint — agenda-aware RAG answer over a user's notes.

The first real cutover target: it calls exactly the same domain function the bot
uses in-process today (`search_service.answer`), now reachable over the private
API. The bot itself is unchanged; `api_client.ApiClient.search` is the seam that
will call this later.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends

from services import user_service
from services import search_service
from api.deps import require_internal_token
from api.schemas import SearchRequest, SearchResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal",
    tags=["search"],
    dependencies=[Depends(require_internal_token)],
)


@router.post("/search", response_model=SearchResponse)
def search(req: SearchRequest) -> SearchResponse:
    # All per-user attributes are resolved server-side from user_id.
    tz, language = user_service.settings(req.user_id)
    now = datetime.now(tz)
    answer = search_service.answer(
        req.user_id, req.query, now, language=language, tz=tz,
    )
    logger.info(
        "API search user=%s len=%d -> %s",
        req.user_id, len(req.query), "hit" if answer else "miss",
    )
    return SearchResponse(answer=answer)
