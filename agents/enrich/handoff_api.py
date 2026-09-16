"""Stateless handoff API for the enrichment specialist (used by the chat agent).

Scheduling is not here — reminders are their own specialist (`agents/reminder/`).

`plan_action` decides the single write a natural-language instruction implies
without executing anything; `execute_action` runs a planned write after approval.
Client-agnostic — the caller passes the user's clock/locale.
"""

import logging

from agents.contracts import ToolResult
from agents.contracts.handoff import HandoffRequest
from agents.runtime.execute_tool import execute_tool
from tools import enrich as tools
from tools.enrich import TOOL_SPECS
from common import helper
from agents.enrich import graph as graphs
from agents.enrich.prompts import planning_messages
from agents.enrich.state import UserContext, context_to_dict

logger = logging.getLogger(__name__)


def _normalize_request(value, now=None, tz=None, locale: str = "en") -> HandoffRequest:
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


def plan_action(user_id: int, request, now, tz, locale) -> dict | None:
    """One-shot: decide the single write action a natural-language instruction
    implies. Returns {name, args, summary} for a write tool, or None if no
    concrete action could be determined. Does not execute anything."""

    try:
        result = graphs.ACTION_PLAN_GRAPH.invoke({
            "messages": planning_messages(_normalize_request(request, now, tz, locale)),
            "user_context": {
                "user_id": user_id,
                "now": now.isoformat() if hasattr(now, "isoformat") else now,
                "tz": str(tz),
                "locale":locale,
            },
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

    return _tool_text(execute_tool(
        tools.TOOLS, {
            "user_id": user_id,
            "now": now.isoformat() if hasattr(now, "isoformat") else now,
            "tz": str(tz),
            "locale":locale,
        },
        action["name"],
        action.get("args") or {},
        "enrich"))
