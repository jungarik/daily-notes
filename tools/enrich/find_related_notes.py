"""find_related_notes enrichment tool."""

import config
from common import embedings, helper
from agents.contracts import ToolResult
from tools.enrich import db


def invoke(context: dict, args: dict) -> ToolResult:
    error = helper.required_values_error(context, "context", ["user_id"])

    if error:
        return ToolResult({"error": error})

    error = helper.required_values_error(args, "args", ["text"])

    if error:
        return ToolResult({"error": error})

    text = (args.get("text") or "").strip()

    if not text:
        return ToolResult({"error": "Error: text is required."})

    embedding = embedings.embed(text)
    note_id = args.get("exclude_note_id")
    rows = (
        db.similar_notes(
            context["user_id"],
            embedding,
            int(note_id),
            limit=config.ENRICH_SIMILAR_LIMIT,
        )
        if note_id is not None
        else db.related_notes(
            context["user_id"],
            embedding,
            config.ENRICH_SIMILAR_LIMIT,
        )
    )

    return ToolResult({"notes": rows})
