"""
Search endpoint — agenda-aware RAG answer over the caller's notes (under /api).
Per-user attributes (timezone, language) are resolved server-side.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends

from services import user_service
from services import search_service
from api.deps import current_user
from api.schemas import SearchRequest, SearchResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["search"])


@router.post("/search", response_model=SearchResponse)
def search(req: SearchRequest, user_id: int = Depends(current_user)) -> SearchResponse:
    tz, language = user_service.settings(user_id)
    now = datetime.now(tz)
    answer = search_service.answer(user_id, req.query, now, language=language, tz=tz)
    logger.info("API search user=%s len=%d -> %s",
                user_id, len(req.query), "hit" if answer else "miss")
    return SearchResponse(answer=answer)
