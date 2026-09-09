"""Typed, serializable context passed from Conversation to specialist agents."""

from typing import TypedDict


class HandoffContract(TypedDict):
    instruction: str
    conversation_summary: str
    referenced_note_ids: list[int]
    citations: list[dict]
    resolved_entities: dict
    locale: str
    timezone: str | None
    now: str | None


def normalize(value, now=None, tz=None, locale: str = "en") -> HandoffContract:
    """Accept the typed contract or upgrade an older plain instruction."""
    if isinstance(value, dict):
        data = dict(value)
    else:
        data = {"instruction": str(value or "")}
    note_ids = []
    for note_id in data.get("referenced_note_ids") or []:
        try:
            note_ids.append(int(note_id))
        except (TypeError, ValueError):
            pass
    return {
        "instruction": str(data.get("instruction") or "").strip(),
        "conversation_summary": str(data.get("conversation_summary") or ""),
        "referenced_note_ids": note_ids,
        "citations": list(data.get("citations") or []),
        "resolved_entities": dict(data.get("resolved_entities") or {}),
        "locale": str(data.get("locale") or locale or "en"),
        "timezone": data.get("timezone") or (str(tz) if tz is not None else None),
        "now": data.get("now") or (now.isoformat() if hasattr(now, "isoformat") else None),
    }
