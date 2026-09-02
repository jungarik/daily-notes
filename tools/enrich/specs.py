"""OpenAI tool schemas and write classification for the enrichment agent."""

WRITE_TOOLS = {
    "create_note",
    "set_note_path",
    "enrich_note",
    "create_reminder",
    "add_note_tags",
    "link_notes",
}

METADATA_CONTEXT_TOOLS = {
    "get_note_context",
    "list_paths",
    "list_tags",
    "get_vault_context",
    "find_related_notes",
}


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


TOOL_SPECS = [
    _fn(
        "list_paths",
        "List the user's existing vault folder paths (with counts), "
        "so you reuse one instead of inventing a parallel path.",
        {},
        [],
    ),
    _fn(
        "list_tags",
        "List the user's existing tags (with counts) so you can reuse them.",
        {},
        [],
    ),
    _fn(
        "get_note_context",
        "Read one user-owned note before moving or enriching it.",
        {"note_id": {"type": "integer"}},
        ["note_id"],
    ),
    _fn(
        "create_note",
        "Create one atomic Zettelkasten note from the given text "
        "(chunked + embedded). The text must contain one idea only, 1-3 short "
        "sentences, without expanded explanation or invented description. If the "
        "user gives several independent ideas, ask for clarification instead. "
        "Requires user confirmation.",
        {"text": {"type": "string"}},
        ["text"],
    ),
    _fn(
        "set_note_path",
        "Move a note to a different vault path (must start with a root "
        "folder). Requires user confirmation.",
        {
            "note_id": {"type": "integer"},
            "path": {"type": "string"},
        },
        ["note_id", "path"],
    ),
    _fn(
        "add_note_tags",
        "Add one or more tags to an existing note without replacing "
        "its current tags. Use get_note_context if the target note needs resolving, "
        "and list_tags to reuse existing tag names when possible. Requires user confirmation.",
        {
            "note_id": {"type": "integer"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        ["note_id", "tags"],
    ),
    _fn(
        "enrich_note",
        "Analyze a note and propose exact metadata (type, title, vault "
        "path, tags, priority). The proposed values require user confirmation before saving.",
        {"note_id": {"type": "integer"}},
        ["note_id"],
    ),
    _fn(
        "link_notes",
        "Link a source note to other related notes. Pass note_id (the "
        "source note being linked, usually a referenced note from the handoff); the "
        "graph proposes semantically related candidates and the user picks which ones "
        "to link. Optionally pass linked_note_ids to pre-select specific targets. "
        "Requires user confirmation.",
        {
            "note_id": {"type": "integer"},
            "linked_note_ids": {
                "type": "array",
                "items": {"type": "integer"},
            },
        },
        ["note_id"],
    ),
    _fn(
        "create_reminder",
        "Create or attach a reminder after confirmation. "
        "Pass the reminder request text; the graph resolves remind_at before approval.",
        {
            "text": {"type": "string"},
            "remind_at": {"type": "string"},
            "note_id": {"type": "integer"},
        },
        ["text"],
    ),
]
