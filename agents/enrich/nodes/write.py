"""Write proposal and validation nodes for Enrich workflows."""

import logging
import re
import uuid

import config
from tools.enrich import db
from agents.enrich.state import ActionPlanState, EnrichState, context_from_state

logger = logging.getLogger(__name__)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…。！？])\s+")


def _atomic_note_text(text: str) -> str:
    """Keep generated create_note proposals small and atomic before confirmation."""
    value = " ".join(line.strip() for line in str(text or "").splitlines()
                     if line.strip())
    if not value:
        return ""
    sentences = _SENTENCE_SPLIT.split(value)
    value = " ".join(sentences[:config.ATOMIC_NOTE_MAX_SENTENCES]).strip()
    if len(value) <= config.ATOMIC_NOTE_MAX_CHARS:
        return value
    shortened = value[:config.ATOMIC_NOTE_MAX_CHARS].rsplit(" ", 1)[0].strip()
    return shortened.rstrip(" ,.;:-") + "..."


def _guardrail_call(call: dict) -> dict:
    """Normalize write-tool arguments that must be safe before confirmation."""
    if call["name"] != "create_note":
        return call

    args = dict(call.get("args") or {})
    args["text"] = _atomic_note_text(args.get("text") or "")

    return {**call, "args": args}


def summarize_write(name: str, args: dict) -> str:
    if name == "create_note":
        return "Create a note: “%s”." % args.get("text", "").strip()

    if name == "set_note_path":
        return "Move note %s to “%s”." % (
            args.get("note_id"),
            args.get("path", "").strip(),
        )

    if name == "add_note_tags":
        return "Add tags %s to note %s." % (
            args.get("tags") or [],
            args.get("note_id"),
        )

    if name == "enrich_note":
        if args.get("title"):
            return "Apply metadata to note %s: “%s” (%s) at “%s”, tags %s." % (
                args.get("note_id"),
                args.get("title"),
                args.get("type"),
                args.get("path"),
                args.get("tags") or [],
            )

        return "Enrich note %s (classify type/title/path/tags)." % args.get("note_id")

    if name == "create_reminder":
        return "Create a reminder for %s: “%s”." % (
            args.get("remind_at"),
            (args.get("text") or "").strip(),
        )

    return "Run %s with %s." % (name, args)


def prepare(state: EnrichState) -> dict:
    call = _guardrail_call(state["tool_call"])
    summary = summarize_write(call["name"], call["args"])
    pending = {"action_id": str(uuid.uuid4()), "tool_call_id": call["id"],
               "name": call["name"], "args": call["args"], "summary": summary}
    logger.info("enrich agent pausing for confirmation: %s user=%s",
                call["name"], state["context"]["user_id"])
    action = {"name": call["name"], "args": call["args"], "summary": summary}
    return {"status": "confirm", "action": action, "pending": pending,
            "tool_call": None}


def validate(state: ActionPlanState) -> dict:
    call = _guardrail_call(state["tool_call"])
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
                       "summary": summarize_write(call["name"], call["args"])},
            "tool_call": None}
