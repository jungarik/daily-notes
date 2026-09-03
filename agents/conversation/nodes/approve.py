"""Approve node: human approval, then idempotent execution via the specialist.

Interrupts the graph with the staged action, resumes on the user's decision, and
executes it exactly once through the owning specialist (or records a decline). A
select action (link_notes) carries the user's chosen note ids. The only public
entry point is `run`.
"""

from langgraph.types import interrupt

from agents.bootstrap import registry
from agents.conversation.state import ChatState, context_from_state, context_update
from agents.runtime import execution_ledger


def _decision(raw) -> tuple:
    """Split a resume value into (approved, selection). The client may send a
    bare bool, or a dict carrying a selection of note ids for a select action."""
    if isinstance(raw, dict):
        return bool(raw.get("approve")), raw.get("selection")

    return bool(raw), None


def _with_selection(action: dict, selection) -> dict:
    """For a select action (link_notes), replace its targets with the user's pick."""
    if selection is None or action.get("name") != "link_notes":
        return action

    chosen = []

    for value in selection:
        try:
            note_id = int(value)
        except (TypeError, ValueError):
            continue

        if note_id not in chosen:
            chosen.append(note_id)

    return {**action, "args": {**action.get("args", {}), "linked_note_ids": chosen}}


def _execute(pending: dict, ctx) -> str:
    service = registry.get("enrich")
    action = _with_selection(pending["action"], pending.get("selection"))

    return execution_ledger.execute_once(
        pending["action_id"],
        ctx.user_id,
        "enrich",
        action,
        lambda: service.execute_action(
            ctx.user_id,
            action,
            ctx.now,
            ctx.tz,
            ctx.locale,
        ),
    )


def run(state: ChatState) -> dict:
    pending = state.get("pending")

    if not pending:
        return {
            "status": "answer",
            "reply": "There is no action to confirm.",
            "action": None,
            "tool_call": None,
        }

    approved, selection = _decision(interrupt({
        "action_id": pending["action_id"],
        "agent": pending.get("agent", "enrich"),
        "action": pending["action"],
        "summary": pending.get("summary"),
    }))
    ctx = context_from_state(state)

    if approved:
        result = _execute({**pending, "selection": selection}, ctx)
    else:
        result = "The user declined this action; do not perform it. Acknowledge and continue."

    message = {
        "role": "tool",
        "tool_call_id": pending["tool_call_id"],
        "content": str(result),
    }

    return {
        "messages": [*state["messages"], message],
        "pending": None,
        "action": None,
        "completed_action_id": pending["action_id"],
        "status": "answer",
        **context_update(ctx),
    }
