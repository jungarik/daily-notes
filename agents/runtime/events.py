"""One entry in a turn's event list, and the reducer that accumulates them.

Every node emits only the events *it* produced; LangGraph's reducer appends them
to the channel. A node therefore never reads the event list to rebuild it, which
is what makes the emission safe when two nodes run in the same super-step — a
read-modify-write would silently drop one of them.

Declare the channel once per state:

    class SomeState(TypedDict, total=False):
        events: Annotated[list[dict], append]

This module is pure: no I/O, no module state, no mapping of domain objects.
"""

from operator import add

# The reducer for an event channel. `operator.add` concatenates the accumulated
# list (left) with the node's emission (right); named here so a state schema
# reads as intent rather than arithmetic.
append = add


def event(node: str, status: str, kind: str = "node", **fields) -> dict:
    """One event: which node, how it went, and whatever that kind carries."""
    return {
        "kind": kind,
        "node": node,
        "status": status,
        **fields,
    }


def failed(events: list[dict], node: str) -> bool:
    """Whether a named node already reported a failure in this turn."""
    return any(
        item.get("node") == node and item.get("status") == "error"
        for item in events or []
    )
