"""get_note_context enrichment tool."""

from common import helper
from tools.enrich import db


def invoke(context: dict, args: dict) -> str:
    error = helper.required_values_error(context, "context", ["user_id"])

    if error:
        return error

    error = helper.required_values_error(args, "args", ["note_id"])

    if error:
        return error

    note_id = args.get("note_id")

    if note_id is None:
        return "Error: note_id is required."

    note = db.get_note_for_user(context["user_id"], int(note_id))

    return helper.json_text(note) if note else "Error: note not found."
