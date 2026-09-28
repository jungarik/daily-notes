"""Tool schema and write classification for the classifier agent.

One write and the reads that resolve it. `enrich_note` moved here from the
enricher: filing a note is this agent's whole job, and leaving a second copy
behind would give the farm two ways to classify — the duplicate-path shape the
structure tests exist to catch.
"""

WRITE_TOOLS = {
    "enrich_note",
}

# Internal workflow tools: a graph node invokes these deterministically, they
# are never offered to the model in TOOL_SPECS. The allowlist is what keeps a
# node from reaching the write tool through the same seam.
CONTEXT_TOOLS = {
    "get_note_context",
    "list_paths",
    "list_tags",
    "get_vault_context",
    "find_related_notes",
    "read_state",
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
        "enrich_note",
        "Analyze a note and propose exact metadata (type, title, vault "
        "path, tags, priority). The proposed values require user confirmation "
        "before saving.",
        {"note_id": {"type": "integer"}},
        ["note_id"],
    ),
]
