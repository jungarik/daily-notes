"""list_paths conversation tool."""

import config
import i18n
from common import helper
from agents.contracts import ToolResult
from tools.conversation import db


def _known_paths(user_id: int) -> list[str]:
    _, raw_language = db.get_user_settings(user_id)
    locale = i18n.normalize(raw_language) or i18n.DEFAULT_LOCALE
    roots = {i18n.t(locale, key) for key in config.ROOT_FOLDERS}
    paths = [name for name, _ in db.list_paths(user_id)]
    paths.extend(name for name in roots if name not in paths)

    return paths


def invoke(context: dict, args: dict) -> ToolResult:
    error = helper.required_values_error(
        context,
        "context",
        ["user_id"],
    )

    if error:
        return ToolResult({"error": error})

    error = helper.required_values_error(args, "args", [])

    if error:
        return ToolResult({"error": error})

    user_id = context["user_id"]

    return ToolResult({"paths": _known_paths(user_id)})
