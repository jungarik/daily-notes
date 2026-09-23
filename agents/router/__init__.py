"""Routing: who runs the next hop.

Three cases, cheapest first (see `devdoc/agent-broker.md`): the responder when
the turn is finishing, an entry tool when the previous model call already chose
one, and only otherwise a model picking from the roster.

`Router` is the public surface; `agents/bootstrap.py` builds it and hands it the
case-3 callable. That callable, `select_agent_name`, now lives in the same
module and is imported from it directly — it used to be withheld here to keep
the OpenAI client out of this import, which merging made moot: importing
`Router` reaches the gateway either way.

The shapes routing moves around live in `agents/contracts/`, and the loop that
calls this lives in `agents/runtime/broker.py` — neither is re-exported here,
so every type and every collaborator has exactly one import path.
"""

from agents.router.agent import Router

__all__ = ["Router"]
