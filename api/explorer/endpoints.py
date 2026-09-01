"""Explorer router — GET /api/explorer. The user's notes for the folder tree."""

from fastapi import APIRouter, Depends

from api.deps import current_user
from api.explorer import helper
from api.explorer.schemas import ExplorerNote

router = APIRouter(prefix="/api/explorer", tags=["explorer"])


@router.get("", response_model=list[ExplorerNote])
def list_notes(user_id: int = Depends(current_user)) -> list[ExplorerNote]:
    return [ExplorerNote(**it) for it in helper.list_for_tree(user_id)]
