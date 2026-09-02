"""Public enrichment tool interface."""

from tools.enrich import (
    add_note_tags,
    create_note,
    create_reminder,
    enrich_note,
    find_related_notes,
    get_note_context,
    get_vault_context,
    link_notes,
    list_paths,
    list_tags,
    set_note_path,
)
from tools.enrich.specs import METADATA_CONTEXT_TOOLS, TOOL_SPECS, WRITE_TOOLS

TOOLS = {
    "list_paths": list_paths.invoke,
    "list_tags": list_tags.invoke,
    "get_note_context": get_note_context.invoke,
    "get_vault_context": get_vault_context.invoke,
    "find_related_notes": find_related_notes.invoke,
    "create_note": create_note.invoke,
    "set_note_path": set_note_path.invoke,
    "add_note_tags": add_note_tags.invoke,
    "enrich_note": enrich_note.invoke,
    "create_reminder": create_reminder.invoke,
    "link_notes": link_notes.invoke,
}


__all__ = [
    "TOOL_SPECS",
    "WRITE_TOOLS",
    "METADATA_CONTEXT_TOOLS",
    "TOOLS",
]
