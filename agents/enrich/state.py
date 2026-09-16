"""State and context helpers for enrichment graphs."""

from datetime import datetime
from typing import Literal, TypedDict
from zoneinfo import ZoneInfo


class UserContext:
    def __init__(self, user_id: int, now, tz=None, locale: str = "en"):
        self.user_id = user_id
        self.now = now
        self.tz = tz
        self.locale = locale


class EnrichState(TypedDict, total=False):
    messages: list[dict]
    user_context: dict
    steps: int
    tool_call: dict | None
    model_error: str | None
    status: Literal["answer", "confirm"]
    reply: str
    action: dict | None
    pending: dict | None
    completed_action_id: str | None
    link_proposal: dict
    metadata_text: str
    metadata_note_id: int | None
    metadata_context: dict
    raw_metadata: dict
    metadata: dict
    metadata_error: str | None
    metadata_trace: list[dict]


class ActionPlanState(TypedDict, total=False):
    messages: list[dict]
    user_context: dict
    tool_specs: list[dict]
    steps: int
    tool_call: dict | None
    model_error: str | None
    action: dict | None
    link_proposal: dict
    metadata_text: str
    metadata_note_id: int | None
    metadata_context: dict
    raw_metadata: dict
    metadata: dict
    metadata_error: str | None
    metadata_trace: list[dict]


class MetadataState(TypedDict, total=False):
    user_id: int
    metadata_text: str
    metadata_note_id: int | None
    metadata_context: dict
    raw_metadata: dict
    metadata: dict
    metadata_error: str | None
    metadata_trace: list[dict]
    tool_call: dict | None
    context: dict


def context_to_dict(ctx: UserContext) -> dict:
    now = ctx.now.isoformat() if hasattr(ctx.now, "isoformat") else ctx.now

    return {
        "user_id": ctx.user_id,
        "now": now,
        "tz": str(ctx.tz) if ctx.tz is not None else None,
        "locale": ctx.locale,
    }


def _restore(value, factory):
    try:
        return factory(value)
    except Exception:
        return value


def context_from_state(state: EnrichState | ActionPlanState) -> UserContext:
    data = state.get("user_context") or {}

    return UserContext(
        data["user_id"],
        _restore(data.get("now"), datetime.fromisoformat),
        tz=_restore(data.get("tz"), ZoneInfo),
        locale=data.get("locale") or "en",
    )


def initial_state(ctx: UserContext, messages: list, pending: dict | None = None) -> EnrichState:
    action = None

    if pending:
        action = {
            "name": pending["name"],
            "args": pending["args"],
            "summary": pending["summary"],
        }

    return {
        "user_context": context_to_dict(ctx),
        "messages": list(messages),
        "steps": 0,
        "tool_call": None,
        "pending": pending,
        "action": action,
        "completed_action_id": None,
    }
