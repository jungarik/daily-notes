"""list_reminders conversation tool."""

from common import helper
from agents.contracts import ToolResult
from tools.conversation import db


def invoke(context: dict, args: dict) -> ToolResult:
    error = helper.required_values_error(
        context,
        "context",
        ["user_id"],
    )

    if error:
        return ToolResult({"error": error})

    error = helper.required_values_error(args, "args", [])

    if error:
        return ToolResult({"error": error})

    user_id = context["user_id"]
    rows = db.upcoming_reminders(user_id)
    result = []

    for row in rows:
        result.append({
            "id": row[0],
            "remind_at": row[1],
            "text": row[2],
            "status": row[3],
        })

    return ToolResult(
        {"reminders": result} if result else {"message": "No upcoming reminders."},
    )
