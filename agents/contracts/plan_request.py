"""The typed input an agent's planning graph is given.

Shared by `enricher` and `reminder`, which both plan a single write from a
natural-language instruction plus whatever context the turn had already
resolved. It is a contract, not a mapper — each agent builds its own from the
`AgentRequest` it was handed — so it stays shared without breaking the
no-shared-domain rule.

`prior_states` is what *earlier agents in this same turn* produced, keyed by
agent name: the finder's answer and the notes it matched, so a write can be
planned against a search that already happened instead of repeating it — and a
peer's own write, planned or performed, so the second half of "note this and
remind me about it" knows which note "it" is. A turn reaches that second case
after a confirm: the approved write finishes as an ordinary `done` hop and the
loop keeps routing, so the next agent finds it in the history.

The history carries only refs, so this is read through `read_state` and is
bounded by the planner's own `may_read`. Each agent keeps only the fields it can
use — a debug trace is not evidence, and would only fill the prompt.
"""

from typing import TypedDict


class PlanRequest(TypedDict):
    instruction: str
    conversation_summary: str
    referenced_note_ids: list[int]
    citations: list[dict]
    resolved_entities: dict
    prior_states: dict[str, dict]
    locale: str
    timezone: str | None
    now: str | None
