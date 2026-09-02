"""Conversation tool schemas and routing groups."""

ENRICH_HANDOFF_TOOLS = {"perform_action"}
REMINDER_HANDOFF_TOOLS = {"set_reminder"}


def _fn(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


HANDOFF_TOOL_SPECS = [
    _fn(
        "perform_action",
        "Create a note, move a note, add tags, link a note to related notes, or "
        "classify/enrich a note. Pass the request verbatim, and include the id of "
        "any note the user is acting on in referenced_note_ids; a specialist "
        "proposes it for confirmation.",
        {
            "instruction": {"type": "string"},
            "referenced_note_ids": {
                "type": "array",
                "items": {"type": "integer"},
            },
            "resolved_entities": {"type": "object"},
        },
        ["instruction"],
    ),
    _fn(
        "set_reminder",
        "Schedule a reminder. Pass the full request including all "
        "date and time details; Enrich proposes it for confirmation.",
        {
            "instruction": {"type": "string"},
            "referenced_note_ids": {
                "type": "array",
                "items": {"type": "integer"},
            },
            "resolved_entities": {"type": "object"},
        },
        ["instruction"],
    ),
]

READ_TOOL_SPECS = [
    _fn(
        "search_notes",
        "Retrieve relevant note evidence for a grounded answer. "
        "After this tool returns, answer only from its evidence.",
        {"query": {"type": "string"}},
        ["query"],
    ),
    _fn(
        "get_note",
        "Fetch one note by id.",
        {"note_id": {"type": "integer"}},
        ["note_id"],
    ),
    _fn(
        "neighbors",
        "List notes directly linked to a note.",
        {"note_id": {"type": "integer"}},
        ["note_id"],
    ),
    _fn(
        "list_reminders",
        "List upcoming active reminders.",
        {},
        [],
    ),
    _fn(
        "list_agenda",
        "List reminders in a specific local date/time range. Use this "
        "for questions about today, tomorrow, a week, or another period. `end_at` "
        "is exclusive; resolve relative dates using the current time in the system prompt.",
        {
            "start_at": {
                "type": "string",
                "description": "ISO-8601 date/time with offset",
            },
            "end_at": {
                "type": "string",
                "description": "Exclusive ISO-8601 date/time with offset",
            },
        },
        ["start_at", "end_at"],
    ),
    _fn(
        "list_paths",
        "List existing vault paths.",
        {},
        [],
    ),
]

TOOL_SPECS = [*READ_TOOL_SPECS, *HANDOFF_TOOL_SPECS]
