"""Shared helpers for the Enrich write nodes.

Guardrails (atomic note text), localized confirmation summaries, and the
link-candidate lookup used by link/stage/validate.
"""

import re
from datetime import datetime

import config
import i18n
from agents.enrich.nodes.write import _rank
from common import embedings
from tools.enrich import db

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


def _link_candidates(user_id: int, note: dict, preselect_ids: list[int],
                     locale: str | None = None) -> tuple:
    """Return (candidates, preselected_ids) for a link proposal.

    Retrieval recalls the source note's nearest semantic neighbours; `_rank`
    then reorders them by the idea each one shares with the source note, so
    conceptual links are offered before merely same-topic notes. Preselected
    ids are the caller's explicit targets when given, otherwise the ranked
    idea-level matches (falling back to the distance threshold when ranking
    produced nothing).
    """
    text = (note.get("text") or note.get("title") or "").strip()
    rows = []

    if text:
        rows = db.link_candidates(
            user_id,
            embedings.embed(text),
            note["id"],
            config.LINK_RECALL_LIMIT,
        )

    ranked = _rank.rank(note, rows, locale)[:config.ENRICH_SIMILAR_LIMIT]
    candidates = [{
        "note_id": row["note_id"],
        "title": row["title"],
        "path": row.get("path"),
        "tags": row.get("tags") or [],
        "distance": row.get("distance"),
        "reason": row.get("reason") or "",
    } for row in ranked]
    by_id = {item["note_id"] for item in candidates}

    owned = db.owned_note_ids(user_id, preselect_ids) if preselect_ids else set()
    owned_preselect = [note_id for note_id in preselect_ids if note_id in owned]

    for note_id in owned_preselect:
        if note_id not in by_id:
            meta = db.get_note_for_user(user_id, note_id)

            if meta:
                candidates.append({
                    "note_id": note_id,
                    "title": meta.get("title") or "note",
                    "path": meta.get("path"),
                    "tags": meta.get("tags") or [],
                    "distance": None,
                    "reason": "",
                })
                by_id.add(note_id)

    if owned_preselect:
        preselected = owned_preselect
    elif any("idea_link" in row for row in ranked):
        # Ranking ran: trust its verdict, including "nothing genuinely connects".
        preselected = [row["note_id"] for row in ranked
                       if row.get("idea_link")][:config.LINK_PRESELECT_LIMIT]
    else:
        preselected = [
            item["note_id"]
            for item in candidates
            if item["distance"] is not None
            and item["distance"] <= config.ENRICH_SIMILAR_MAX_DISTANCE
        ]

    return candidates, preselected


def link_action(user_id: int, call: dict, locale: str | None = None) -> dict:
    """Validate a link_notes call and enrich its args with pickable candidates.

    Returns either an action dict (kind='select') or a tool error message dict.
    """
    args = dict(call.get("args") or {})

    try:
        note_id = int(args.get("note_id"))
    except (TypeError, ValueError):
        note_id = None

    note = db.get_note_for_user(user_id, note_id) if note_id is not None else None

    if note is None:
        return {"error": "Error: choose a valid user-owned source note id."}

    preselect_ids = []

    for value in args.get("linked_note_ids") or []:
        try:
            candidate = int(value)
        except (TypeError, ValueError):
            continue

        if candidate != note_id and candidate not in preselect_ids:
            preselect_ids.append(candidate)

    candidates, preselected = _link_candidates(user_id, note, preselect_ids, locale)

    if not candidates:
        return {"error": "Error: no related notes were found to link."}

    args["note_id"] = note_id
    args["candidates"] = candidates
    args["linked_note_ids"] = preselected

    return {
        "name": "link_notes",
        "args": args,
        "summary": summarize_write("link_notes", args, locale),
        "kind": "select",
    }


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
