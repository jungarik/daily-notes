"""The responder's own tool: reading what earlier hops in the turn produced.

`read_state` is deterministic — the responder's node calls it before its single
model call, never the model itself. It is therefore in `CONTEXT_TOOLS` and
absent from `TOOL_SPECS`; the allowlist in `execute_allowed_tool` is what keeps
a model-driven path from reaching it.

It lives in its own namespace rather than the responder's folder for the same
reason every other tool does (see CLAUDE.md), and is named for its one caller.
If a second agent ever needs to read a peer's state, the namespace is what
moves — the tool itself already takes the reader's `may_read` as a parameter.
"""

from tools.responder import read_state

TOOLS = {
    "read_state": read_state.invoke,
}

CONTEXT_TOOLS = {"read_state"}

TOOL_SPECS = []

WRITE_TOOLS = set()

__all__ = ["TOOLS", "TOOL_SPECS", "WRITE_TOOLS", "CONTEXT_TOOLS"]
