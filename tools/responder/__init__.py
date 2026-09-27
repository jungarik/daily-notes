"""The responder's own tool: reading what earlier hops in the turn produced.

`read_state` is deterministic — the responder's node calls it before its single
model call, never the model itself. It is therefore in `CONTEXT_TOOLS` and
absent from `TOOL_SPECS`; the allowlist in `execute_allowed_tool` is what keeps
a model-driven path from reaching it.

The enricher and reminder read peer state too, and carry their own copy of this
tool rather than importing this one — the same trade `db.py` makes (see
CLAUDE.md). The tool takes the reader's `may_read` as a parameter, so the copies
differ only in which vertical owns them.
"""

from tools.responder import read_state

TOOLS = {
    "read_state": read_state.invoke,
}

CONTEXT_TOOLS = {"read_state"}

TOOL_SPECS = []

WRITE_TOOLS = set()

__all__ = ["TOOLS", "TOOL_SPECS", "WRITE_TOOLS", "CONTEXT_TOOLS"]
