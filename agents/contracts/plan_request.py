"""The typed input an agent's planning graph is given.

Shared by `enrich` and `reminder`, which both plan a single write from a
natural-language instruction plus whatever context the turn had already
resolved. It is a contract, not a mapper — each agent builds its own from the
`AgentRequest` it was handed — so it stays shared without breaking the
no-shared-domain rule.
"""

from typing import TypedDict


class PlanRequest(TypedDict):
    instruction: str
    conversation_summary: str
    referenced_note_ids: list[int]
    citations: list[dict]
    resolved_entities: dict
    locale: str
    timezone: str | None
    now: str | None
