"""The finder agent's tools: owner-scoped reads over the user's own notes.

Every tool here answers a question; none of them writes. A turn that needs a
write is routed to the agent that owns it by the broker, not by a tool call from
here.
"""

from tools.finder import (
    detect_reminder,
    get_note,
    list_agenda,
    list_paths,
    list_reminders,
    neighbors,
    search_notes,
)
from tools.finder.specs import READ_TOOL_SPECS

TOOLS = {
    "search_notes": search_notes.invoke,
    "get_note": get_note.invoke,
    "neighbors": neighbors.invoke,
    "list_reminders": list_reminders.invoke,
    "list_agenda": list_agenda.invoke,
    "list_paths": list_paths.invoke,
    "detect_reminder": detect_reminder.invoke,
}


__all__ = ["READ_TOOL_SPECS", "TOOLS"]
