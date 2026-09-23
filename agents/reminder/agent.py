"""The reminder agent's seat in the farm.

Adapts the reminder vertical to the two broker contracts and nothing more:
`start` plans the write the user's message implies and pauses for confirmation,
`resume` performs it once the user has approved. Everything reminder-specific —
the planning graph, the prompts, the tools — stays where it already lives.

The resume token is this agent's own business: here it is the planned action,
because that is all this agent needs to finish. The broker never opens it.

Nothing in this module imports another agent.
"""

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from agents.broker.contracts import AgentRequest, AgentResult, AgentSpec, Ref, UserContext
from agents.contracts import ToolResult
from agents.reminder import handoff_api
from agents.reminder.state import Ctx, context_to_dict
from agents.runtime.execute_tool import execute_tool
from tools import reminder as tools

logger = logging.getLogger(__name__)

NAME = "reminder"

DESCRIPTION = (
    "Schedules a reminder for a time the user described in words. Use when the "
    "request is about being reminded, alerted, or nudged at some point in the "
    "future. Does not create or edit note content.")


def _restore_clock(context: UserContext) -> tuple:
    """The caller's clock and locale, restored from the envelope's plain JSON."""
    raw_now = context.get("now")
    now = datetime.fromisoformat(raw_now) if isinstance(raw_now, str) else raw_now
    raw_tz = context.get("tz")
    tz = ZoneInfo(raw_tz) if isinstance(raw_tz, str) and raw_tz else None

    return now, tz, context.get("locale") or "en"


def _build_plan_request(request: AgentRequest, now, tz, locale: str) -> dict:
    """The planning contract, from the envelope the broker handed over.

    The material the caller had already resolved arrives in `references`; the
    clock and locale arrive in `context`.
    """
    references = request.references

    return {
        "instruction": request.message,
        "conversation_summary": references.get("conversation_summary") or "",
        "referenced_note_ids": references.get("referenced_note_ids") or [],
        "citations": references.get("citations") or [],
        "resolved_entities": dict(references.get("resolved_entities") or {}),
        "locale": locale,
        "timezone": str(tz) if tz is not None else None,
        "now": now.isoformat() if hasattr(now, "isoformat") else None,
    }


def _collect_refs(data: dict) -> tuple[Ref, ...]:
    """What the write made, as the history sees it. Only ids the tool confirmed."""
    made = []

    for kind, key in (("reminder", "reminder_id"), ("note", "note_id")):
        value = data.get(key)

        if value is not None:
            made.append(Ref(kind=kind, id=str(value)))

    return tuple(made)


def start(request: AgentRequest) -> AgentResult:
    """Plan the reminder the message implies and pause for confirmation."""
    now, tz, locale = _restore_clock(request.context)

    action = handoff_api.plan_action(
        request.context["user_id"],
        _build_plan_request(request, now, tz, locale),
        now,
        tz,
        locale)

    if action is None:
        return AgentResult(
            status="done",
            state={"planned": None, "message": request.message})

    return AgentResult(
        status="needs_input",
        state={"planned": action, "message": request.message},
        ask={"kind": "confirm", "action": action, "summary": action.get("summary")},
        token=json.dumps(action, default=str))


def resume(token: str, decision: dict, context: UserContext) -> AgentResult:
    """Perform the approved write and report what it made.

    The broker calls this only on approval and only once per action, so there is
    no decline branch and no idempotency check here.
    """
    action = json.loads(token)
    now, tz, locale = _restore_clock(context)
    result = execute_tool(
        tools.TOOLS,
        context_to_dict(Ctx(context["user_id"], now, tz=tz, locale=locale)),
        action["name"],
        action.get("args") or {},
        NAME)

    # `execute_tool` degrades to a plain string when the tool is unknown or
    # raised, so anything that is not a ToolResult is a failure, not a quiet
    # success with nothing to report.
    if not isinstance(result, ToolResult):
        return AgentResult(status="failed", state={"action": action}, error=str(result))

    data = result.data or {}

    if data.get("error"):
        return AgentResult(status="failed", state={"action": action}, error=data["error"])

    return AgentResult(
        status="done",
        state={"action": action, "result": data},
        produced=_collect_refs(data))


SPEC = AgentSpec(
    name=NAME,
    description=DESCRIPTION,
    start=start,
    resume=resume,
    entry_tools=("set_reminder",),
    may_read=("conversation",),
)
