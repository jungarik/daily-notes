"""Stateless handoff API for the reminder specialist (used by the chat agent).

`plan_action` resolves the time an instruction implies and returns the
`create_reminder` write it produces, without executing anything;
`execute_action` runs that write after approval. Client-agnostic — the caller
passes the user's clock/locale.

Every read goes through `tools/reminder/`; this agent owns no SQL.
"""

import logging

from agents.contracts import ToolResult
from agents.contracts.handoff import HandoffRequest
from agents.runtime.execute_tool import execute_allowed_tool, execute_tool
from common import helper
from agents.reminder.graph import PLAN_GRAPH
from agents.reminder.state import Ctx, context_to_dict
from tools import reminder as tools

logger = logging.getLogger(__name__)


def _normalize(value, now=None, tz=None, locale: str = "en") -> HandoffRequest:
    """Accept the typed contract or upgrade an older plain instruction."""
    if isinstance(value, dict):
        data: dict = dict(value)
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


def _tool_text(result) -> str:
    if isinstance(result, ToolResult):
        return helper.json_text(result.data)

    return str(result)


def _referenced_note(result, note_id: int) -> dict | None:
    """The note a context tool returned, keyed as the planner expects it, or None
    when the tool could not read it."""
    if not isinstance(result, ToolResult):
        return None

    note = result.data or {}

    if note.get("error"):
        return None

    return {**note, "note_id": note.get("id", note_id)}


def _referenced_notes(context: dict, note_ids: list[int]) -> list[dict]:
    """Hydrate the notes an instruction points at, one context tool call each."""
    notes = []

    for note_id in note_ids:
        note = _referenced_note(
            execute_allowed_tool(
                tools.TOOLS,
                tools.CONTEXT_TOOLS,
                context,
                "get_note_context",
                {"note_id": note_id},
                "reminder",
            ),
            note_id,
        )

        if note is not None:
            notes.append(note)

    return notes


def plan_action(user_id: int, request, now, tz, locale) -> dict | None:
    """One-shot: resolve the reminder an instruction implies. Returns
    {name, args, summary}, or None when no time could be resolved."""
    contract = _normalize(request, now, tz, locale)
    contract["resolved_entities"]["referenced_notes"] = _referenced_notes(
        context_to_dict(Ctx(user_id, now, tz=tz, locale=locale)),
        contract["referenced_note_ids"])

    try:
        result = PLAN_GRAPH.invoke({
            "contract": contract,
            "now": now,
            "locale": locale,
            "action": None,
            "events": [],
        })
    except Exception:
        logger.exception("plan_action failed for user %s", user_id)

        return None

    if result["action"] is None:
        logger.info("no reminder planned for user %s: %s", user_id, result["events"])

    return result["action"]


def execute_action(user_id: int, action: dict, now, tz, locale) -> str:
    """Run an approved reminder write. Returns the tool's result string."""
    ctx = Ctx(user_id, now, tz=tz, locale=locale)

    return _tool_text(execute_tool(
        tools.TOOLS,{
            "user_id": ctx.user_id,
            "now": ctx.now.isoformat() if hasattr(ctx.now, "isoformat") else ctx.now,
            "tz": str(ctx.tz) if ctx.tz is not None else None,
            "locale": ctx.locale,
        },
        action["name"],
        action.get("args") or {},
        "reminder",
    ))
