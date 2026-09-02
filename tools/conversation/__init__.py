"""Tool declarations and execution entry point used by Conversation."""

from tools.conversation import (
    get_note,
    list_agenda,
    list_paths,
    list_reminders,
    neighbors,
    search_notes,
)
from tools.conversation.specs import (
    ENRICH_HANDOFF_TOOLS,
    HANDOFF_TOOL_SPECS,
    READ_TOOL_SPECS,
    REMINDER_HANDOFF_TOOLS,
    TOOL_SPECS,
)

TOOLS = {
    "search_notes": search_notes.invoke,
    "get_note": get_note.invoke,
    "neighbors": neighbors.invoke,
    "list_reminders": list_reminders.invoke,
    "list_agenda": list_agenda.invoke,
    "list_paths": list_paths.invoke,
}


__all__ = [
    "ENRICH_HANDOFF_TOOLS", "HANDOFF_TOOL_SPECS",
    "READ_TOOL_SPECS", "REMINDER_HANDOFF_TOOLS", "TOOL_SPECS",
    "TOOLS",
]
