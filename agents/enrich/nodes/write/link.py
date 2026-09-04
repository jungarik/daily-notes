"""link_context node: gather selectable link candidates before a link_notes write.

Retrieval (embeddings + nearest-neighbour lookup) and the idea-level ranking
pass that reorders its results live here, out of the stage/validate nodes —
mirroring how enrich_note gathers classify context first.
The proposal (or an error) is stashed for the downstream node. Single public
`run`.
"""

from agents.enrich.nodes.write import _shared
from agents.enrich.state import context_from_state


def run(state) -> dict:
    ctx = context_from_state(state)
    proposal = _shared.link_action(ctx.user_id, state["tool_call"], ctx.locale)

    return {"link_proposal": proposal}
