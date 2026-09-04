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
    call = _shared.guardrail_call(state["tool_call"])

    if call["name"] == "link_notes":
        error = _shared.link_error(state, call)

        if error:
            return {**error, "pending": None}

        proposal = state["link_proposal"]
        args, summary, kind = proposal["args"], proposal["summary"], "select"
    else:
        locale = context_from_state(state).locale
        args = call["args"]
        summary = _shared.summarize_write(call["name"], call["args"], locale)
        kind = None

    pending = {"action_id": str(uuid.uuid4()), "tool_call_id": call["id"],
               "name": call["name"], "args": args, "summary": summary}
    logger.info("enrich agent pausing for confirmation: %s user=%s",
                call["name"], state["context"]["user_id"])
    action = {"name": call["name"], "args": args, "summary": summary}

    if kind:
        action["kind"] = kind

    return {"status": "confirm", "action": action, "pending": pending,
            "tool_call": None}
