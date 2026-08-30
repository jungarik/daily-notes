"""Response models for the header section."""

from pydantic import BaseModel


class HeaderStats(BaseModel):
    notes: int = 0
    links: int = 0
    reminders: int = 0
