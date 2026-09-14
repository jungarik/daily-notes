"""Entering a compiled agent graph — shared by every agent.

A run is entered in one of three ways: `invoke` starts a fresh turn from an
initial state, `resume` answers an approval the graph is parked on, and `retry`
re-enters an unfinished run at the node it stopped on. The bound on a run lives
in `graph_config` (see `checkpoint.graph_config`), so this module holds no agent
configuration of its own.
"""

from langgraph.types import Command


def invoke(graph, graph_config: dict, state) -> dict:
    """Run a fresh turn from the given initial state."""
    return graph.invoke(state, graph_config)


def resume(graph, graph_config: dict, decision) -> dict:
    """Resume a paused approval. `decision` is a bool (approve), or a dict
    carrying the approval plus a selection, e.g.
    {"approve": bool, "selection": [...]}."""
    return graph.invoke(Command(resume=decision), graph_config)


def retry(graph, graph_config: dict) -> dict:
    """Re-enter an unfinished run at the node it stopped on."""
    return graph.invoke(None, graph_config)
