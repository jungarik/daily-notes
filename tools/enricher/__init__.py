"""Public enrichment tool interface."""

from tools.enricher import (
    add_note_tags,
    create_note,
    enrich_note,
    filter_owned_notes,
    find_link_candidates,
    find_related_notes,
    get_note_context,
    get_vault_context,
    link_notes,
    list_paths,
    list_tags,
    set_note_path,
)
from tools.enricher.specs import (
    CONTEXT_TOOLS, METADATA_CONTEXT_TOOLS, TOOL_SPECS, WRITE_TOOLS,
)

TOOLS = {
    "list_paths": list_paths.invoke,
    "list_tags": list_tags.invoke,
    "get_note_context": get_note_context.invoke,
    "get_vault_context": get_vault_context.invoke,
    "find_related_notes": find_related_notes.invoke,
    "find_link_candidates": find_link_candidates.invoke,
    "filter_owned_notes": filter_owned_notes.invoke,
    "create_note": create_note.invoke,
    "set_note_path": set_note_path.invoke,
    "add_note_tags": add_note_tags.invoke,
    "enrich_note": enrich_note.invoke,
    "link_notes": link_notes.invoke,
}


__all__ = [
    "TOOL_SPECS",
    "WRITE_TOOLS",
    "CONTEXT_TOOLS",
    "METADATA_CONTEXT_TOOLS",
    "TOOLS",
]
