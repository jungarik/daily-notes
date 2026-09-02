"""add_note_tags enrichment tool."""

from common import helper
from tools.enrich import db


def _clean_tags(tags) -> list[str]:
    cleaned = []
    seen = set()

    for tag in tags or []:
        value = str(tag or "").strip().lower()

        if not value or value in seen:
            continue

        cleaned.append(value)
        seen.add(value)

    return cleaned


def invoke(context: dict, args: dict) -> str:
    error = helper.required_values_error(context, "context", ["user_id"])

    if error:
        return error

    error = helper.required_values_error(args, "args", ["note_id", "tags"])

    if error:
        return error

    note_id = args.get("note_id")
    tags = args.get("tags")

    if note_id is None or not tags:
        return "Error: note_id and tags are required."

    note_id = int(note_id)
    note = db.get_note_for_user(context["user_id"], note_id)

    if not note:
        return "Error: note not found."

    additions = _clean_tags(tags)

    if not additions:
        return "Error: at least one non-empty tag is required."

    current = _clean_tags(note.get("tags") or [])
    current_set = set(current)
    merged = current + [
        tag
        for tag in additions
        if tag not in current_set
    ]
    db.set_tags(note_id, merged)

    return helper.json_text({
        "ok": True,
        "note_id": note_id,
        "tags": merged,
    })
