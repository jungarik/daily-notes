"""Stateless handoff API for the enrichment specialist (used by the chat agent).

`plan_action` decides the single write a natural-language instruction implies
without executing anything; `execute_action` runs a planned write after approval.
Client-agnostic — the caller passes the user's clock/locale.
"""

import logging

from agents.contracts import ToolResult
from agents.contracts import handoff
from agents.runtime.execute_tool import execute_tool
from tools import enrich as tools
from tools.enrich import TOOL_SPECS
from common import helper
from agents.enrich import graph as loop
from agents.enrich import db
from agents.enrich.prompts import planning_messages
from agents.enrich.state import Ctx, context_to_dict

logger = logging.getLogger(__name__)


def _tool_text(result) -> str:
    if isinstance(result, ToolResult):
        return helper.json_text(result.data)

    return str(result)


def plan_action(user_id: int, request, now, tz, locale) -> dict | None:
    """One-shot: decide the single write action a natural-language instruction
    implies. Returns {name, args, summary} for a write tool, or None if no
    concrete action could be determined. Does not execute anything."""
    contract = handoff.normalize(request, now, tz, locale)
    if (contract.get("resolved_entities") or {}).get("specialist_mode") == "reminder":
        notes = []
        for note_id in contract["referenced_note_ids"]:
            note = db.get_note_for_user(user_id, note_id)
            if note:
                note = dict(note)
                note["note_id"] = note.get("id", note_id)
                notes.append(note)
        contract["resolved_entities"]["referenced_notes"] = notes
        result = loop.REMINDER_PLAN_GRAPH.invoke({
            "contract": contract, "now": now, "action": None,
            "reminder_trace": [], "locale": locale,
        })
        return result.get("action")
    ctx = Ctx(user_id, now, tz=tz, locale=locale)
    messages = planning_messages(contract)
    try:
        result = loop.ACTION_PLAN_GRAPH.invoke({
            "messages": messages,
            "context": context_to_dict(ctx),
            "tool_specs": TOOL_SPECS,
            "steps": 0,
            "tool_call": None,
            "action": None,
        })
        return result.get("action")
    except Exception:
        logger.exception("plan_action failed for user %s", user_id)
        return None


def execute_action(user_id: int, action: dict, now, tz, locale) -> str:
    """Run a planned write action (after the user approved it). Returns the tool's
    result string."""
    ctx = Ctx(user_id, now, tz=tz, locale=locale)

    return _tool_text(execute_tool(
        tools.TOOLS,
        context_to_dict(ctx),
        action["name"],
        action.get("args") or {},
        "enrich",
    ))
