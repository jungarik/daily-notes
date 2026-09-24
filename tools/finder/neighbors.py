"""neighbors: the notes linked to one note, with enough of each to answer from.

A Zettelkasten answer usually lives one link away from the note the search
found, so this returns each neighbour's full text rather than a stub. That is
what lets a turn answer from the links without spending a `get_note` step per
neighbour — a budget of six steps does not stretch to four lookups.

Full text is unbounded per note, so the list is capped (`LIMIT`) and says when
the cap cut it. A note with more links than that is a hub, and searching it is
a better move than enumerating it.
"""

from common import helper
from agents.contracts import ToolResult
from tools.finder import db

# Each row carries a whole note, so this bounds the size of one tool result.
LIMIT = 25


def invoke(context: dict, args: dict) -> ToolResult:
    if error := helper.required_values_error(context, "context", ["user_id"]):
        return ToolResult({"error": error})

    if error := helper.required_values_error(args, "args", ["note_id"]):
        return ToolResult({"error": error})

    user_id = context["user_id"]
    note_id = args.get("note_id")
    # One more than the cap, so a full page is told apart from an exact fit
    # without a second count query.
    rows = db.links_of_for_user(user_id, int(note_id), LIMIT + 1)
    truncated = len(rows) > LIMIT
    notes = []
    citations = []

    for neighbour_id, title, text, path, created, direction, links in rows[:LIMIT]:
        date = created.isoformat() if hasattr(created, "isoformat") else created
        notes.append({
            "id": neighbour_id,
            "title": title or "untitled",
            "text": text,
            "path": path,
            "date": date,
            "direction": direction,
            "links": links,
        })
        citations.append({
            "note_id": neighbour_id,
            "title": helper.note_label(title, text),
            "path": path,
            "date": date,
        })

    if not notes:
        return ToolResult({"message": "No linked notes."})

    # `truncated` is always present rather than only when true: a reader that
    # has to infer "the field is missing, so nothing was cut" will eventually
    # infer it wrong.
    return ToolResult({"notes": notes, "truncated": truncated}, citations=citations)
