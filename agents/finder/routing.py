"""Conditional edges for the finder graph.

A plain ReAct loop with no pause — the farm owns approvals, so there is no
`approve` edge and no entry branch to resume one:

    START ──────────────▶ reason
    reason ─after_reason─▶ act | END
    act ────────────────▶ reason
"""

from langgraph.graph import END

from agents.finder.state import FinderState


def after_reason(state: FinderState):
    """Run a read tool, or answer and finish."""
    return END if state.get("tool_call") is None else "act"
