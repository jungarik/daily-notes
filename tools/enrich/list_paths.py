"""list_paths enrichment tool."""

from common import helper
from tools.enrich import db


def invoke(context: dict, _args: dict) -> str:
    error = helper.required_values_error(context, "context", ["user_id"])

    if error:
        return error

    error = helper.required_values_error(_args, "args", [])

    if error:
        return error

    rows = db.list_paths(context["user_id"])

    if not rows:
        return "No existing paths."

    result = []

    for path, count in rows:
        result.append({
            "path": path,
            "count": count,
        })

    return helper.json_text(result)
