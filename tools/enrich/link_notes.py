"""link_notes enrichment tool.

Create directed related-links from one source note to one or more selected
target notes. The link table is read as bidirectional, so a single directed
edge per target is enough. The chat flow lets the user pick which candidate
targets to link before this write runs.
"""

from common import helper
from agents.contracts import ToolResult
from tools.enrich import db


def _clean_ids(values, exclude: int) -> list[int]:
    cleaned = []
    seen = set()

    for value in values or []:
        try:
            note_id = int(value)
        except (TypeError, ValueError):
            continue

        if note_id == exclude or note_id in seen:
            continue

        cleaned.append(note_id)
        seen.add(note_id)

    return cleaned


def invoke(context: dict, args: dict) -> ToolResult:
    error = helper.required_values_error(context, "context", ["user_id"])

    if error:
        return ToolResult({"error": error})

    error = helper.required_values_error(args, "args", ["note_id"])

    if error:
        return ToolResult({"error": error})

    note_id = args.get("note_id")

    if note_id is None:
        return ToolResult({"error": "Error: note_id is required."})

    note_id = int(note_id)
    user_id = context["user_id"]

    if db.get_note_for_user(user_id, note_id) is None:
        return ToolResult({"error": "Error: note not found."})

    target_ids = _clean_ids(args.get("linked_note_ids"), note_id)

    if not target_ids:
        return ToolResult({"error": "Error: select at least one note to link."})

    owned = db.owned_note_ids(user_id, target_ids)
    missing = [note for note in target_ids if note not in owned]

    if missing:
        return ToolResult({
            "error": "Error: notes not found: %s." % ", ".join(str(m) for m in missing),
        })

    linked = db.create_links(note_id, target_ids)

    return ToolResult({
        "ok": True,
        "note_id": note_id,
        "linked_note_ids": linked,
    })
