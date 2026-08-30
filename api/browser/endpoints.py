"""Browser router — GET /api/browser. The user's notes for the folder tree."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import current_user
from api.browser import helper

router = APIRouter(prefix="/api/browser", tags=["browser"])


class BrowserNote(BaseModel):
    id: int
    title: str
    path: str | None = None
    snippet: str = ""
    created_at: str | None = None
    links: int = 0


@router.get("", response_model=list[BrowserNote])
def list_notes(user_id: int = Depends(current_user)) -> list[BrowserNote]:
    return [BrowserNote(**it) for it in helper.list_for_tree(user_id)]
