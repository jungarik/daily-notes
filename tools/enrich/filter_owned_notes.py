"""filter_owned_notes enrichment tool.

An internal workflow tool, not offered to the model: it answers which of the
given note ids belong to the caller, so a node never has to ask the database.
"""

from common import helper
from agents.contracts import ToolResult
from tools.enrich import db


def invoke(context: dict, args: dict) -> ToolResult:
    error = helper.required_values_error(context, "context", ["user_id"])

    if error:
        return ToolResult({"error": error})

    note_ids = []

    for note_id in args.get("note_ids") or []:
        try:
            note_ids.append(int(note_id))
        except (TypeError, ValueError):
            continue

    owned = db.owned_note_ids(context["user_id"], note_ids) if note_ids else set()

    return ToolResult({"note_ids": [
        note_id for note_id in note_ids if note_id in owned
    ]})
