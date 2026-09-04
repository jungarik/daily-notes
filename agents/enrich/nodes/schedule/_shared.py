"""Shared state helpers for the schedule (reminder) nodes."""

from agents.enrich.state import EnrichState, ReminderPlanState, context_from_state


def latest_user_text(messages: list[dict]) -> str:
    for message in reversed(messages or []):
        if message.get("role") == "user":
            return message.get("content") or ""

    return ""


def now(state) -> object:
    if state.get("now") is not None:
        return state["now"]

    return context_from_state(state).now


def locale(state) -> str | None:
    """Locale from EnrichState context or the reminder plan state's own field."""
    ctx = state.get("context")

    if ctx and ctx.get("locale"):
        return ctx["locale"]

    return state.get("locale")


def contract(state: ReminderPlanState | EnrichState) -> dict:
    if state.get("contract"):
        return state["contract"]

    call = state.get("tool_call") or {}
    args = call.get("args") or {}
    instruction = latest_user_text(state.get("messages") or [])

    if not instruction:
        instruction = (args.get("text") or "").strip()

    resolved = {}

    if args.get("note_id") is not None:
        resolved["referenced_notes"] = [{"note_id": int(args["note_id"])}]

    return {"instruction": instruction, "resolved_entities": resolved}
