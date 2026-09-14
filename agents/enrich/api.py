"""Standalone fast-capture surface for the enrichment specialist.

Analyses a thought into an editable proposal, applies the user's edits, and
persists an approved proposal exactly once through the execution ledger. Nothing
here runs the interactive loop — chat handoffs go through `handoff_api`, and the
graph-driven turn flow is owned by its calling section.
"""

import json
import logging
import uuid

from agents.contracts import CaptureProposal
from agents.runtime import execution_ledger
from common import embedings
from common import helper
from agents.enrich import db
from agents.enrich.graph import CLASSIFY_GRAPH

logger = logging.getLogger(__name__)

EDITABLE_CAPTURE_FIELDS = {"text", "title", "path", "tags", "type", "priority",
                           "linked_note_ids"}


# ----- standalone fast-capture API (transport adapters call these) --------

def _capture_proposal(args: dict, related_notes: list[dict]) -> CaptureProposal:
    title = args["title"]
    return {
        "action_id": str(uuid.uuid4()),
        "status": "proposed",
        "action": {
            "name": "capture_thought",
            "args": args,
            "summary": f"Capture “{title}” in {args['path']}.",
        },
        "related_notes": [{
            "note_id": item["note_id"],
            "title": item["title"],
            "path": item.get("path"),
            "distance": item["distance"]} for item in related_notes
        ],
    }


def propose_capture(user_id: int, text: str) -> CaptureProposal:
    """Analyze a thought and return an editable preview. Nothing is persisted."""
    text = text.strip()

    if not text:
        raise ValueError("text is required")

    result = CLASSIFY_GRAPH.invoke({
        "user_id": user_id,
        "metadata_text": text,
        "metadata_note_id": None,
        "metadata_trace": [],
    })
    args = {"text": text, **result["metadata"], "linked_note_ids": []}
    related = (result.get("metadata_context") or {}).get("related_notes") or []

    return _capture_proposal(args, related)


def revise_capture(user_id: int, proposal: CaptureProposal,
                   changes: dict) -> CaptureProposal:
    """Apply user edits and return a new proposal with its own action identity."""
    unknown = set(changes) - EDITABLE_CAPTURE_FIELDS
    if unknown:
        raise ValueError("Unsupported capture fields: " + ", ".join(sorted(unknown)))
    if proposal.get("action", {}).get("name") != "capture_thought":
        raise ValueError("Not a capture proposal")
    args = {**proposal["action"]["args"], **changes}
    text = (args.get("text") or "").strip()
    if not text:
        raise ValueError("text is required")
    roots, default_root = helper.localized_root_folders(db.get_language(user_id))
    metadata = helper.normalize(args, text, roots, default_root)
    linked_ids = list(dict.fromkeys(int(value)
                                    for value in args.get("linked_note_ids") or []))
    missing = [note_id for note_id in linked_ids
               if db.get_note_for_user(user_id, note_id) is None]
    if missing:
        raise ValueError("Linked notes were not found for this user: " +
                         ", ".join(str(note_id) for note_id in missing))
    args = {"text": text, **metadata, "linked_note_ids": linked_ids}
    return _capture_proposal(args, list(proposal.get("related_notes") or []))


def _execute_capture(user_id: int, args: dict) -> dict:
    """Validate and persist an approved fast-capture proposal."""
    text = (args.get("text") or "").strip()
    if not text:
        raise ValueError("text is required")
    roots, default_root = helper.localized_root_folders(db.get_language(user_id))
    metadata = helper.normalize({
        "type": args.get("type"),
        "title": args.get("title"),
        "path": args.get("path"),
        "tags": args.get("tags"),
        "priority": args.get("priority"),
    }, text, roots, default_root)
    linked_note_ids = [int(note_id) for note_id in args.get("linked_note_ids") or []]
    return db.save_captured_thought(
        user_id, text, metadata, embedings.build_chunks(text), linked_note_ids)


def confirm_capture(user_id: int, proposal: CaptureProposal) -> dict:
    """Persist an approved proposal once; retries return its recorded result."""
    action = proposal.get("action") or {}
    if action.get("name") != "capture_thought" or not proposal.get("action_id"):
        raise ValueError("Invalid capture proposal")
    args = action.get("args") or {}
    result = execution_ledger.execute_once(
        proposal["action_id"], user_id, "enrich", action,
        lambda: json.dumps(_execute_capture(user_id, args), ensure_ascii=False),
    )
    try:
        data = json.loads(result)
    except (TypeError, json.JSONDecodeError):
        return {"status": "unchanged", "action_id": proposal["action_id"],
                "message": result}
    return {"status": "completed", "action_id": proposal["action_id"], **data}


def cancel_capture(proposal: CaptureProposal) -> dict:
    """Cancel locally. Since proposals do not write, there is nothing to undo."""
    return {"status": "cancelled", "action_id": proposal.get("action_id")}
