"""Tool specs for the reminder agent."""

WRITE_TOOLS = {"create_reminder"}

# Internal workflow tools a node invokes deterministically; never offered to the
# model in TOOL_SPECS.
CONTEXT_TOOLS = {"get_note_context"}

TOOL_SPECS = [{
    "type": "function",
    "function": {
        "name": "create_reminder",
        "description": (
            "Create or attach a reminder after confirmation. Pass the reminder "
            "request text; the graph resolves remind_at before approval."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "remind_at": {"type": "string"},
                "note_id": {"type": "integer"},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
}]
