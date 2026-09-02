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

    for row in rows:
        result.append({
            "id": row[0],
            "title": row[1] or "untitled",
            "direction": row[3],
        })

    return ToolResult(
        {"notes": result} if result else {"message": "No linked notes."},
    )
