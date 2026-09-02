"""get_note_context enrichment tool."""

from common import helper
from agents.contracts import ToolResult
from tools.enrich import db


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

    note = db.get_note_for_user(context["user_id"], int(note_id))

    return ToolResult(note) if note else ToolResult({"error": "Error: note not found."})
