"""OpenAI tool schemas and write classification for the enrichment agent."""

WRITE_TOOLS = {"create_note", "set_note_path", "enrich_note", "create_reminder"}


def _fn(name, description, properties, required):
    return {
              "type": "function",
              "function": {
                "name": name,
                "description": description,
                "parameters": {
                  "type": "object",
                  "properties": properties, 
                  "required": required
              },
    }}


TOOL_SPECS = [
    _fn("list_paths", "List the user's existing vault folder paths (with counts), "
        "so you reuse one instead of inventing a parallel path.", {}, []),
    _fn("list_tags", "List the user's existing tags (with counts) so you can reuse them.", {}, []),
    _fn("get_note_context", "Read one user-owned note before moving or enriching it.",
        {"note_id": {"type": "integer"}}, ["note_id"]),
    _fn("create_note", "Create one atomic Zettelkasten note from the given text "
        "(chunked + embedded). The text must contain one idea only, 1-3 short "
        "sentences, without expanded explanation or invented description. If the "
        "user gives several independent ideas, ask for clarification instead. "
        "Requires user confirmation.", {"text": {"type": "string"}}, ["text"]),
    _fn("set_note_path", "Move a note to a different vault path (must start with a root "
        "folder). Requires user confirmation.",
        {"note_id": {"type": "integer"}, "path": {"type": "string"}},
        ["note_id", "path"]),
    _fn("enrich_note", "Analyze a note and propose exact metadata (type, title, vault "
        "path, tags, priority). The proposed values require user confirmation before saving.",
        {"note_id": {"type": "integer"}}, ["note_id"]),
    _fn("create_reminder", "Create or attach a reminder after confirmation. "
        "Pass the reminder request text; the graph resolves remind_at before approval.",
        {"text": {"type": "string"}, "remind_at": {"type": "string"},
         "note_id": {"type": "integer"}}, ["text"]),
]
