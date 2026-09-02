"""neighbors conversation tool."""

from common import helper
from agents.contracts import ToolResult
from tools.conversation import db


def invoke(context: dict, args: dict) -> ToolResult:
    if error := helper.required_values_error(context, "context", ["user_id"]):
        return ToolResult({"error": error})

    if error := helper.required_values_error(args, "args", ["note_id"]):
        return ToolResult({"error": error})

    user_id = context["user_id"]
    note_id = args.get("note_id")
    rows = db.links_of_for_user(user_id, int(note_id))
    result = []
    citations = []

    for row in rows:
        neighbour_id, title, text, path, created, direction = row
        result.append({
            "id": neighbour_id,
            "title": title or "untitled",
            "direction": direction,
        })
        citations.append({
            "note_id": neighbour_id,
            "title": helper.note_label(title, text),
            "path": path,
            "date": created.isoformat() if hasattr(created, "isoformat") else created,
        })

    return ToolResult(
        {"notes": result} if result else {"message": "No linked notes."},
        citations=citations,
    )
