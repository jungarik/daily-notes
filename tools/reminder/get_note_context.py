"""get_note_context tool for the reminder agent."""

from common import helper
from agents.contracts import ToolResult
from tools.reminder import db


def invoke(context: dict, args: dict) -> ToolResult:
    error = helper.required_values_error(context, "context", ["user_id"])

    if error:
        return ToolResult({"error": error})

    error = helper.required_values_error(args, "args", ["note_id"])

    if error:
        return ToolResult({"error": error})

    note = db.get_note_for_user(context["user_id"], int(args["note_id"]))

    return ToolResult(note) if note else ToolResult({"error": "Error: note not found."})
