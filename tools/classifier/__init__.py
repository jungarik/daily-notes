"""Public classifier tool interface.

One write — `enrich_note` — and the reads that resolve it: the vault vocabulary
a note is filed against (`list_paths`, `list_tags`, `get_vault_context`), the
note itself (`get_note_context`), its nearest neighbours as classification
precedent (`find_related_notes`), and `read_state` for what earlier hops in the
turn found.

Every one of these is duplicated from `tools/enricher/` rather than imported
from it, for the reason CLAUDE.md gives for `db.py`: a vertical owns its own
tool surface so one agent's cannot ripple into another's. `enrich_note` is the
exception that is *moved*, not copied — two ways to file a note would be two
ways for the farm to disagree with itself.
"""

from tools.classifier import (
    enrich_note,
    find_related_notes,
    get_note_context,
    get_vault_context,
    list_paths,
    list_tags,
    read_state,
)
from tools.classifier.specs import CONTEXT_TOOLS, TOOL_SPECS, WRITE_TOOLS

TOOLS = {
    "list_paths": list_paths.invoke,
    "list_tags": list_tags.invoke,
    "get_note_context": get_note_context.invoke,
    "get_vault_context": get_vault_context.invoke,
    "find_related_notes": find_related_notes.invoke,
    "enrich_note": enrich_note.invoke,
    "read_state": read_state.invoke,
}


__all__ = [
    "TOOL_SPECS",
    "WRITE_TOOLS",
    "CONTEXT_TOOLS",
    "TOOLS",
]
