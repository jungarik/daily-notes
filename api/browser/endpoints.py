"""Browser router — GET /api/browser. The user's notes for the folder tree."""

from fastapi import APIRouter, Depends

from api.deps import current_user
from api.browser import helper
from api.browser.schemas import BrowserNote

router = APIRouter(prefix="/api/browser", tags=["browser"])


@router.get("", response_model=list[BrowserNote])
def list_notes(user_id: int = Depends(current_user)) -> list[BrowserNote]:
    return [BrowserNote(**it) for it in helper.list_for_tree(user_id)]
