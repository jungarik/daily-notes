"""Tool schemas for the finder agent.

Read tools only. The controller this namespace was built for could also call
`perform_action` / `set_reminder` to hand a write to a named specialist; the
loop's router owns that decision now, so those specs are gone and an agent
here names no peer.
"""


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
        "Notes directly linked to a note, each with its full text, title, path, "
        "date, link direction and its own link count. Read a linked note from "
        "here rather than calling `get_note` on it. Capped at 25; `truncated` "
        "says the note has more links than were returned.",
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
    _fn(
        "detect_reminder",
        "Deterministically check whether a message is a reminder request "
        "(reminder intent plus a time expression). Cheap — no model call. Use it "
        "to answer a question about whether something is a reminder.",
        {"text": {"type": "string"}},
        ["text"],
    ),
]
