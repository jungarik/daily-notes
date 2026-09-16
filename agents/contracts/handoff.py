"""Typed, serializable context passed from Conversation to specialist agents."""

from typing import TypedDict


class HandoffRequest(TypedDict):
    instruction: str
    conversation_summary: str
    referenced_note_ids: list[int]
    citations: list[dict]
    resolved_entities: dict
    locale: str
    timezone: str | None
    now: str | None
