"""validate_write node: validate a planned write into an action (plan graph).

A plain ownership/args check that turns the model's chosen write tool into a
concrete action, or loops back with a tool error. Single public `run`.
"""

from tools.enrich import db
from agents.enrich.nodes.write import _shared
from agents.enrich.state import ActionPlanState, context_from_state


def run(state: ActionPlanState) -> dict:
    call = _shared.guardrail_call(state["tool_call"])

    if call["name"] == "link_notes":
        error = _shared.link_error(state, call)

        if error:
            return error

        return {"action": state["link_proposal"], "tool_call": None}

    if call["name"] in {"set_note_path", "enrich_note", "add_note_tags"}:
        try:
            note_id = int(call["args"].get("note_id"))
        except (TypeError, ValueError):
            note_id = None

        if note_id is None or not db.get_note_for_user(
                context_from_state(state).user_id, note_id):
            message = {"role": "tool", "tool_call_id": call["id"],
                       "content": "Error: choose a valid user-owned note id from "
                                  "the handoff or read tools."}

            return {"messages": [*state["messages"], message],
                    "tool_call": None, "action": None}

    return {"action": {"name": call["name"], "args": call["args"],
                       "summary": _shared.summarize_write(call["name"], call["args"],
                                                          context_from_state(state).locale)},
            "tool_call": None}
