"""find_link_candidates enrichment tool.

An internal workflow tool, not offered to the model: the `link_context` node
calls it to recall neighbours carrying enough body text for idea-level ranking.
"""

import config
from common import embedings, helper
from agents.contracts import ToolResult
from tools.enrich import db


def invoke(context: dict, args: dict) -> ToolResult:
    error = helper.required_values_error(context, "context", ["user_id"])

    if error:
        return ToolResult({"error": error})

    error = helper.required_values_error(args, "args", ["text", "exclude_note_id"])

    if error:
        return ToolResult({"error": error})

    text = (args.get("text") or "").strip()

    if not text:
        return ToolResult({"notes": []})

    return ToolResult({"notes": db.link_candidates(
        context["user_id"],
        embedings.embed(text),
        int(args["exclude_note_id"]),
        int(args.get("limit") or config.LINK_RECALL_LIMIT),
    )})
