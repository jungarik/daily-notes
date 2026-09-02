"""Write proposal and validation nodes for Enrich workflows."""

import logging
import re
import uuid

import config
from common import embedings
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


def _marker(note_id) -> str:
    """A note reference the web app renders as a clickable preview card."""
    return "[[note:%s]]" % note_id


def summarize_write(name: str, args: dict) -> str:
    if name == "create_note":
        return "Create a note: “%s”." % args.get("text", "").strip()

    if name == "set_note_path":
        return "Move this note to “%s”:\n%s" % (
            args.get("path", "").strip(),
            _marker(args.get("note_id")),
        )

    if name == "add_note_tags":
        return "Add tags %s to this note:\n%s" % (
            args.get("tags") or [],
            _marker(args.get("note_id")),
        )

    if name == "enrich_note":
        if args.get("title"):
            return "Apply metadata “%s” (%s) at “%s”, tags %s to this note:\n%s" % (
                args.get("title"),
                args.get("type"),
                args.get("path"),
                args.get("tags") or [],
                _marker(args.get("note_id")),
            )

        return "Enrich this note (classify type/title/path/tags):\n%s" % (
            _marker(args.get("note_id")),
        )

    if name == "create_reminder":
        base = "Create a reminder for %s: “%s”." % (
            args.get("remind_at"),
            (args.get("text") or "").strip(),
        )

        if args.get("note_id"):
            return "%s\n%s" % (base, _marker(args.get("note_id")))

        return base

    if name == "link_notes":
        return "Link this note to the notes you select below:\n%s" % (
            _marker(args.get("note_id")),
        )

    return "Run %s with %s." % (name, args)


def _link_candidates(user_id: int, note: dict, preselect_ids: list[int]) -> tuple:
    """Return (candidates, preselected_ids) for a link proposal.

    Candidates are the source note's nearest semantic neighbours. Preselected
    ids are the caller's explicit targets when given, otherwise the neighbours
    within the enrichment distance threshold.
    """
    text = (note.get("text") or note.get("title") or "").strip()
    rows = []

    if text:
        rows = db.similar_notes(
            user_id,
            embedings.embed(text),
            note["id"],
            limit=config.ENRICH_SIMILAR_LIMIT,
        )

    candidates = [{
        "note_id": row["note_id"],
        "title": row["title"],
        "path": row.get("path"),
        "tags": row.get("tags") or [],
        "distance": row.get("distance"),
    } for row in rows]
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
                })
                by_id.add(note_id)

    if owned_preselect:
        preselected = owned_preselect
    else:
        preselected = [
            item["note_id"]
            for item in candidates
            if item["distance"] is not None
            and item["distance"] <= config.ENRICH_SIMILAR_MAX_DISTANCE
        ]

    return candidates, preselected


def _link_action(user_id: int, call: dict) -> dict:
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

    candidates, preselected = _link_candidates(user_id, note, preselect_ids)

    if not candidates:
        return {"error": "Error: no related notes were found to link."}

    args["note_id"] = note_id
    args["candidates"] = candidates
    args["linked_note_ids"] = preselected

    return {
        "name": "link_notes",
        "args": args,
        "summary": summarize_write("link_notes", args),
        "kind": "select",
    }


def link_context(state) -> dict:
    """Deterministically gather link candidates before the write node.

    Retrieval (embeddings + nearest-neighbour lookup) lives here, out of the
    write/validate nodes, mirroring how enrich_note loads metadata_context first.
    The resulting proposal (or an error) is stashed for the downstream node.
    """
    proposal = _link_action(context_from_state(state).user_id, state["tool_call"])

    return {"link_proposal": proposal}


def _link_error(state, call) -> dict | None:
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


def prepare(state: EnrichState) -> dict:
    call = _guardrail_call(state["tool_call"])

    if call["name"] == "link_notes":
        error = _link_error(state, call)

        if error:
            return {**error, "pending": None}

        proposal = state["link_proposal"]
        args, summary, kind = proposal["args"], proposal["summary"], "select"
    else:
        args, summary, kind = call["args"], summarize_write(call["name"], call["args"]), None

    pending = {"action_id": str(uuid.uuid4()), "tool_call_id": call["id"],
               "name": call["name"], "args": args, "summary": summary}
    logger.info("enrich agent pausing for confirmation: %s user=%s",
                call["name"], state["context"]["user_id"])
    action = {"name": call["name"], "args": args, "summary": summary}

    if kind:
        action["kind"] = kind

    return {"status": "confirm", "action": action, "pending": pending,
            "tool_call": None}


def validate(state: ActionPlanState) -> dict:
    call = _guardrail_call(state["tool_call"])

    if call["name"] == "link_notes":
        error = _link_error(state, call)

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
                       "summary": summarize_write(call["name"], call["args"])},
            "tool_call": None}
