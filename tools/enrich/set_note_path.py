"""set_note_path enrichment tool."""

import config
import i18n
from common import helper
from agents.contracts import ToolResult
from tools.enrich import db


def _all_root_names() -> set[str]:
    return {
        i18n.t(locale, key)
        for key in config.ROOT_FOLDERS
        for locale in i18n.SUPPORTED
    }


def _clean_root_path(path: str) -> str | None:
    if not path:
        return None

    parts = [
        part.strip()
        for part in str(path).replace("\\", "/").split("/")
    ]
    parts = [
        part
        for part in parts
        if part and part not in (".", "..")
    ]

    if not parts:
        return None

    roots = {
        name.lower(): name
        for name in _all_root_names()
    }
    canonical = roots.get(parts[0].lower())

    if canonical is None:
        return None

    return "/".join([canonical] + parts[1:])


def invoke(context: dict, args: dict) -> ToolResult:
    error = helper.required_values_error(context, "context", ["user_id"])

    if error:
        return ToolResult({"error": error})

    error = helper.required_values_error(args, "args", ["note_id", "path"])

    if error:
        return ToolResult({"error": error})

    note_id = args.get("note_id")
    path = (args.get("path") or "").strip()

    if note_id is None or not path:
        return ToolResult({"error": "Error: note_id and path are required."})

    cleaned = _clean_root_path(path)

    if cleaned is None:
        return ToolResult({"error": "Error: path must start with a root folder."})

    note_id = int(note_id)

    if db.get_note_for_user(context["user_id"], note_id) is None:
        return ToolResult({"error": "Error: note not found."})

    db.set_path(note_id, cleaned)
    meta = db.get_meta(note_id)

    return ToolResult({
        "ok": True,
        "path": (meta or {}).get("path"),
    })
