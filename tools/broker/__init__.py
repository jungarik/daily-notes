"""Tools the broker offers across the farm, rather than any one agent's own.

`read_state` is deterministic: a node calls it, never the model. It is therefore
in `CONTEXT_TOOLS` and absent from `TOOL_SPECS` — the allowlist in
`execute_allowed_tool` is what keeps a model-driven path from reaching it.
"""

from tools.broker import read_state

TOOLS = {
    "read_state": read_state.invoke,
}

CONTEXT_TOOLS = {"read_state"}

TOOL_SPECS = []

WRITE_TOOLS = set()

__all__ = ["TOOLS", "TOOL_SPECS", "WRITE_TOOLS", "CONTEXT_TOOLS"]
