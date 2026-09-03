"""Tool declarations and execution entry point used by Conversation."""

from tools.conversation import (
    detect_reminder,
    get_note,
    list_agenda,
    list_paths,
    list_reminders,
    neighbors,
    search_notes,
)
from tools.conversation.specs import (
    HANDOFF_SPECIALIST,
    HANDOFF_TOOLS,
    HANDOFF_TOOL_SPECS,
    READ_TOOL_SPECS,
    TOOL_SPECS,
)

TOOLS = {
    "search_notes": search_notes.invoke,
    "get_note": get_note.invoke,
    "neighbors": neighbors.invoke,
    "list_reminders": list_reminders.invoke,
    "list_agenda": list_agenda.invoke,
    "list_paths": list_paths.invoke,
    "detect_reminder": detect_reminder.invoke,
}


__all__ = [
    "HANDOFF_SPECIALIST", "HANDOFF_TOOLS", "HANDOFF_TOOL_SPECS",
    "READ_TOOL_SPECS", "TOOL_SPECS", "TOOLS",
]
