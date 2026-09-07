"""stage node: stage a pending write for approval (interactive graph).

Guardrails the tool args, builds a localized confirmation summary, and returns
the pending action that `approve` will run. Single public `run`.
"""

import logging
import uuid

from agents.enrich.nodes.write import _shared
from agents.enrich.state import EnrichState, context_from_state

logger = logging.getLogger(__name__)


def run(state: EnrichState) -> dict:
    tool_call = _shared.guardrail_call(state.get("tool_call") or {})

    if tool_call["name"] == "link_notes":
        error = _shared.link_error(state, tool_call)

        if error:
            return {**error, "pending": None}

        proposal = state.get("link_proposal") or {}
        args, summary, kind = proposal["args"], proposal["summary"], "select"
    else:
        locale = context_from_state(state).locale
        args = tool_call["args"]
        summary = _shared.summarize_write(tool_call["name"], tool_call["args"], locale)
        kind = None

    pending = {
        "action_id": str(uuid.uuid4()),
        "tool_call_id": tool_call["id"],
        "name": tool_call["name"],
        "args": args,
        "summary": summary,
    }
    logger.info(
        "enrich agent pausing for confirmation: %s user=%s",
        tool_call["name"],
        (state.get("context") or {}).get("user_id"),
    )
    action = {"name": tool_call["name"], "args": args, "summary": summary}

    if kind:
        action["kind"] = kind

    return {
        "status": "confirm",
        "action": action,
        "pending": pending,
        "tool_call": None,
    }
