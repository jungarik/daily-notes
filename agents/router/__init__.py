"""Routing: who runs the next hop.

Three cases, cheapest first (see `devdoc/agent-broker.md`): the responder when
the turn is finishing, an entry tool when the previous model call already chose
one, and only otherwise a model picking from the roster. `Router` is the whole
public surface; `agents/bootstrap.py` builds it.

`model_selector` is deliberately not re-exported: it reaches the OpenAI client
at import time, and importing the router should not drag a network client in
behind it. The composition root imports it directly.

The shapes routing moves around live in `agents/contracts/`, and the loop that
calls this lives in `agents/runtime/broker.py` — neither is re-exported here,
so every type and every collaborator has exactly one import path.
"""

from agents.router.router import Router

__all__ = ["Router"]
