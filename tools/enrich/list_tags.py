"""list_tags enrichment tool."""

from common import helper
from agents.contracts import ToolResult
from tools.enrich import db


def invoke(context: dict, _args: dict) -> ToolResult:
    error = helper.required_values_error(context, "context", ["user_id"])

    if error:
        return ToolResult({"error": error})

    error = helper.required_values_error(_args, "args", [])

    if error:
        return ToolResult({"error": error})

    rows = db.list_tags(context["user_id"])

    if not rows:
        return ToolResult({"message": "No existing tags.", "tags": []})

    result = []

    for tag, count in rows:
        result.append({
            "tag": tag,
            "count": count,
        })

    return ToolResult({"tags": result})
