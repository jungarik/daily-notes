"""Response models for the browser section."""

from pydantic import BaseModel


class BrowserNote(BaseModel):
    id: int
    title: str
    path: str | None = None
    snippet: str = ""
    created_at: str | None = None
    links: int = 0
