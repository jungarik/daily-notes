"""get_vault_context enrichment tool."""

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

    roots, default_root = helper.localized_root_folders(
        db.get_language(context["user_id"])
    )

    return ToolResult({
        "root_folders": roots,
        "default_root": default_root,
    })
