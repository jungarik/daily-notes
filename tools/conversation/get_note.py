"""get_note conversation tool."""

from common import helper
from agents.contracts import ToolResult
from tools.conversation import db


def invoke(
    context: dict,
    args: dict,
) -> ToolResult:
    error = helper.required_values_error(context, "context", ["user_id"])

    if error:
        return ToolResult({"error": error})

    error = helper.required_values_error(args, "args", ["note_id"])

    if error:
        return ToolResult({"error": error})

    user_id = context["user_id"]
    note_id = args.get("note_id")
    note = db.get_note_for_user(user_id, int(note_id))

    if not note:
        return ToolResult({"error": "Error: note not found."})

    return ToolResult(
        {
            "id": note["id"],
            "title": note["title"],
            "path": note["path"],
            "tags": note["tags"],
            "text": note["text"],
        },
        citations=[{
            "note_id": note["id"],
            "title": helper.note_label(
                note.get("title"),
                note.get("text"),
            ),
        }],
    )
