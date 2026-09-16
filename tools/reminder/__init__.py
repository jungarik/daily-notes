"""Tools owned by the reminder agent."""

from tools.reminder import create_reminder, get_note_context
from tools.reminder.specs import CONTEXT_TOOLS, TOOL_SPECS, WRITE_TOOLS

TOOLS = {
    "create_reminder": create_reminder.invoke,
    "get_note_context": get_note_context.invoke,
}

__all__ = ["TOOLS", "TOOL_SPECS", "WRITE_TOOLS", "CONTEXT_TOOLS"]
