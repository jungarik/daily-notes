"""Explorer router — GET /api/explorer: the folder tree's notes, plus the root
roster that orders its top level."""

from fastapi import APIRouter, Depends

from api.deps import current_user
from api.explorer import helper
from api.explorer.schemas import ExplorerNote, ExplorerPayload, VaultRoot

router = APIRouter(prefix="/api/explorer", tags=["explorer"])


@router.get("", response_model=ExplorerPayload)
def list_notes(user_id: int = Depends(current_user)) -> ExplorerPayload:
    return ExplorerPayload(
        notes=[ExplorerNote(**note) for note in helper.list_for_tree(user_id)],
        roots=[VaultRoot(**root) for root in helper.list_roots(user_id)],
    )
