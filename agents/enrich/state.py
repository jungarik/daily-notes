"""State and context helpers for enrichment graphs."""

from datetime import datetime
from typing import Literal, TypedDict
from zoneinfo import ZoneInfo

from agents.enrich.tools import Ctx


class EnrichState(TypedDict, total=False):
    messages: list[dict]
    context: dict
    steps: int
    tool_call: dict | None
    status: Literal["answer", "confirm"]
    reply: str
    action: dict | None
    pending: dict | None
    completed_action_id: str | None
    metadata_text: str
    metadata_note_id: int | None
    metadata_context: dict
    raw_metadata: dict
    metadata: dict
    metadata_error: str | None
    metadata_trace: list[dict]
    reminder_raw: dict
    reminder_error: str | None
    reminder_trace: list[dict]


class ActionPlanState(TypedDict, total=False):
    messages: list[dict]
    context: dict
    tool_specs: list[dict]
    steps: int
    tool_call: dict | None
    action: dict | None
    metadata_text: str
    metadata_note_id: int | None
    metadata_context: dict
    raw_metadata: dict
    metadata: dict
    metadata_error: str | None
    metadata_trace: list[dict]
    reminder_raw: dict
    reminder_error: str | None
    reminder_trace: list[dict]


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


class ReminderPlanState(TypedDict, total=False):
    contract: dict
    now: object
    reminder_raw: dict
    action: dict | None
    reminder_error: str | None
    reminder_trace: list[dict]


def context_data(ctx: Ctx) -> dict:
    now = ctx.now.isoformat() if hasattr(ctx.now, "isoformat") else ctx.now
    return {"user_id": ctx.user_id, "now": now, "tz": str(ctx.tz),
            "locale": ctx.locale}


def _restore(value, factory):
    try:
        return factory(value)
    except Exception:
        return value


def context_from_state(state: EnrichState | ActionPlanState) -> Ctx:
    data = state["context"]
    return Ctx(data["user_id"], _restore(data.get("now"), datetime.fromisoformat),
               tz=_restore(data.get("tz"), ZoneInfo),
               locale=data.get("locale") or "en")


def initial_state(ctx: Ctx, messages: list, pending: dict | None = None) -> EnrichState:
    action = None
    if pending:
        action = {"name": pending["name"], "args": pending["args"],
                  "summary": pending["summary"]}
    return {"context": context_data(ctx), "messages": list(messages), "steps": 0,
            "tool_call": None, "pending": pending, "action": action,
            "completed_action_id": None}
