"""enrich_note enrichment tool."""

import logging

from common import helper
from agents.contracts import ToolResult
from tools.enrich import db

logger = logging.getLogger(__name__)


def invoke(context: dict, args: dict) -> ToolResult:
    error = helper.required_values_error(context, "context", ["user_id"])

    if error:
        return ToolResult({"error": error})

    error = helper.required_values_error(args, "args", ["note_id"])

    if error:
        return ToolResult({"error": error})

    note_id = args.get("note_id")

    if note_id is None:
        return ToolResult({"error": "Error: note_id is required."})

    required = {
        "type",
        "title",
        "path",
        "tags",
        "priority",
    }

    if not required.issubset(args):
        return ToolResult({
            "error": "Error: enrichment proposal is missing approved metadata; regenerate it.",
        })

    note_id = int(note_id)
    note = db.get_note_for_user(context["user_id"], note_id)

    if not note or not (note.get("text") or "").strip():
        return ToolResult({"error": "Error: note not found or empty."})

    root_folders, default_root = helper.localized_root_folders(
        db.get_language(context["user_id"])
    )
    metadata = helper.normalize(
        args,
        note["text"],
        root_folders,
        default_root,
    )
    db.set_metadata(
        note_id,
        metadata["type"],
        metadata["title"],
        metadata["priority"],
        metadata["tags"],
        metadata["path"],
    )
    logger.info(
        "Enriched note %s -> %s '%s' @ %s",
        note_id,
        metadata["type"],
        metadata["title"],
        metadata["path"],
    )

    return ToolResult(metadata)
