"""get_vault_context enrichment tool."""

from common import helper
from agents.contracts import ToolResult
from tools.enricher import db


def invoke(context: dict, _args: dict) -> ToolResult:
    error = helper.required_values_error(context, "context", ["user_id"])

    if error:
        return ToolResult({"error": error})

    error = helper.required_values_error(_args, "args", [])

    if error:
        return ToolResult({"error": error})

    # The caller already resolved the locale and put it in the tool context —
    # reaching back to `users.language` here would let the request's locale and
    # the folder names disagree, and folder names are written into the note's
    # path, so that disagreement is durable.
    roots, default_root = helper.localized_root_folders(context.get("locale"))

    return ToolResult({
        "root_folders": roots,
        "default_root": default_root,
    })
