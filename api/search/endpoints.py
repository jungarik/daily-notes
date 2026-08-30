"""Search router — GET /api/search?q=<query>. Server-side note search."""

from fastapi import APIRouter, Depends, Query

from api.deps import current_user
from api.search import helper
from api.search.schemas import SearchHit

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=list[SearchHit])
def search(q: str = Query(default="", max_length=1000),
           user_id: int = Depends(current_user)) -> list[SearchHit]:
    return [SearchHit(**it) for it in helper.search(user_id, q)]
