"""stage node: stage a pending write for approval (interactive graph).

Guardrails the tool args, builds a localized confirmation summary, and returns
the pending action that `approve` will run. Single public `run`; the helpers
below are pure — `run` is the only place that reads state.
"""

import logging
import re
import uuid
from datetime import datetime

import config
import i18n
from agents.enrich.state import EnrichState, context_from_state

logger = logging.getLogger(__name__)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…。！？])\s+")
_NO_CANDIDATES = "Error: no related notes were found to link."


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


def _tag_text(tags) -> str:
    return ", ".join(tags) if tags else ""


def _summarize_write(name: str, args: dict, locale: str | None = None) -> str:
    """A localized, human-readable summary of a pending write for confirmation.
    Note references are embedded as `[[note:ID]]` markers (rendered as cards)."""
    note_id = args.get("note_id")

    if name == "create_note":
        return i18n.t(locale, "action_create_note", text=args.get("text", "").strip())

    if name == "set_note_path":
        return i18n.t(locale, "action_set_note_path",
                      path=args.get("path", "").strip(), id=note_id)

    if name == "add_note_tags":
        return i18n.t(locale, "action_add_note_tags",
                      tags=_tag_text(args.get("tags")), id=note_id)

    if name == "enrich_note":
        if args.get("title"):
            return i18n.t(locale, "action_enrich_note",
                          title=args.get("title"), type=args.get("type"),
                          path=args.get("path"), tags=_tag_text(args.get("tags")),
                          id=note_id)

        return i18n.t(locale, "action_enrich_note_plain", id=note_id)

    if name == "create_reminder":
        when = args.get("remind_at")

        try:
            when = i18n.fmt_datetime(locale, datetime.fromisoformat(args["remind_at"]))
        except Exception:
            pass

        text = (args.get("text") or "").strip()

        if note_id:
            return i18n.t(locale, "action_create_reminder_note",
                          when=when, text=text, id=note_id)

        return i18n.t(locale, "action_create_reminder", when=when, text=text)

    if name == "link_notes":
        return i18n.t(locale, "action_link_notes", id=note_id)

    return i18n.t(locale, "action_generic", name=name, args=args)


def _declined(messages: list[dict], tool_call_id: str, error: str) -> dict:
    return {
        "messages": [*messages, {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": error,
        }],
        "action": None,
        "tool_call": None,
        "pending": None,
    }


def _staged(tool_call: dict, args: dict, summary: str, kind: str | None) -> dict:
    action = {"name": tool_call["name"], "args": args, "summary": summary}

    if kind:
        action["kind"] = kind

    return {
        "status": "confirm",
        "action": action,
        "pending": {
            "action_id": str(uuid.uuid4()),
            "tool_call_id": tool_call["id"],
            "name": tool_call["name"],
            "args": args,
            "summary": summary,
        },
        "tool_call": None,
    }


def run(state: EnrichState) -> dict:
    tool_call = _guardrail_call(state.get("tool_call") or {})
    messages = state.get("messages") or []

    if tool_call["name"] == "link_notes":
        proposal = state.get("link_proposal") or {"error": _NO_CANDIDATES}

        if "error" in proposal:
            return _declined(messages, tool_call["id"], proposal["error"])

        args, summary, kind = proposal["args"], proposal["summary"], "select"
    else:
        locale = context_from_state(state).locale
        args = tool_call["args"]
        summary = _summarize_write(tool_call["name"], args, locale)
        kind = None

    logger.info(
        "enrich agent pausing for confirmation: %s user=%s",
        tool_call["name"],
        (state.get("context") or {}).get("user_id"),
    )

    return _staged(tool_call, args, summary, kind)
