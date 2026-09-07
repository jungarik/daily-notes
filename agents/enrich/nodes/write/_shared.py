"""Shared helpers for the Enrich write nodes.

Guardrails (atomic note text) and localized confirmation summaries used by
link/stage/validate.
"""

import re
from datetime import datetime

import config
import i18n

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


def guardrail_call(call: dict) -> dict:
    """Normalize write-tool arguments that must be safe before confirmation."""
    if call["name"] != "create_note":
        return call

    args = dict(call.get("args") or {})
    args["text"] = _atomic_note_text(args.get("text") or "")

    return {**call, "args": args}


def _tag_text(tags) -> str:
    return ", ".join(tags) if tags else ""


def summarize_write(name: str, args: dict, locale: str | None = None) -> str:
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


def link_error(state, call) -> dict | None:
    """Return a tool-error patch when the link proposal failed, else None."""
    proposal = state.get("link_proposal") or {
        "error": "Error: no related notes were found to link.",
    }

    if "error" in proposal:
        message = {"role": "tool", "tool_call_id": call["id"],
                   "content": proposal["error"]}

        return {"messages": [*state["messages"], message],
                "action": None, "tool_call": None}

    return None
