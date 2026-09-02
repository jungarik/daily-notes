"""list_agenda conversation tool."""

from datetime import datetime

from common import helper
from agents.contracts import ToolResult
from tools.conversation import db


def _agenda_time(tz, raw, field: str):
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an ISO-8601 date/time")

    if value.tzinfo is None:
        if not hasattr(tz, "utcoffset"):
            raise ValueError(f"{field} must include a UTC offset")

        value = value.replace(tzinfo=tz)

    return value


def invoke(
    context: dict,
    args: dict,
) -> ToolResult:
    error = helper.required_values_error(
        context,
        "context",
        ["user_id", "tz"],
    )

    if error:
        return ToolResult({"error": error})

    error = helper.required_values_error(
        args,
        "args",
        ["start_at", "end_at"],
    )

    if error:
        return ToolResult({"error": error})

    user_id = context["user_id"]
    tz = context["tz"]
    start_at = _agenda_time(tz, args.get("start_at"), "start_at")
    end_at = _agenda_time(tz, args.get("end_at"), "end_at")

    if end_at <= start_at:
        return ToolResult({"error": "Error: end_at must be after start_at."})

    rows = db.agenda_reminders(user_id, start_at, end_at)
    citations = []

    for row in rows:
        citations.append({
            "note_id": row["note_id"],
            "title": helper.note_label(
                row.get("title"),
                row.get("text"),
            ),
        })

    return ToolResult(
        {"reminders": rows} if rows else {"message": "No reminders in that period."},
        citations=citations,
    )
