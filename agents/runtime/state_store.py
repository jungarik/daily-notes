"""Persistence for the turn tree.

This is the loop's own bookkeeping, not an agent's domain data — the same
category as `runtime/execution_ledger.py`, and the same exception to "agents
reach persistence only through tools". No agent imports this module; the loop
is handed it at composition time and is the only caller.

A turn is a tree: every hop writes one row, `causation_id` points at the row that
caused it, and `correlation_id` names the turn they all belong to.
"""

import uuid

from psycopg.types.json import Json

from agents.contracts import HistoryEntry, Ref
from db import cursor


def save(correlation_id: str, 
         causation_id: str | None, 
         user_id: int, 
         agent: str,
         status: str, 
         produced: tuple[Ref, ...], 
         state: dict) -> str:
    """Write one hop's state and return its new `state_id`."""
    state_id = str(uuid.uuid4())

    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_states
                (state_id, correlation_id, causation_id, user_id, agent, status,
                 produced, state)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """,
            (
                state_id,
                correlation_id,
                causation_id,
                user_id,
                agent,
                status,
                Json([{"kind": ref.kind, "id": ref.id} for ref in produced]),
                Json(state),
            ),
        )

    return state_id


def read_history(correlation_id: str) -> tuple[HistoryEntry, ...]:
    """Rebuild the turn's routing view from its saved rows.

    One agent, one entry: a later row for the same agent replaces its earlier
    one, so a confirmed hop supersedes the `needs_input` that preceded it. Both
    rows stay in the table — that is the audit record.

    A rebuilt entry carries no `error`: the table does not store one, so there is
    nothing here to report. Within a single turn the live history holds the real
    text — this path runs only to restore the hops that came *before* a suspend,
    so what is lost is the wording of a failure the user has already been told
    about. Its `status` survives, which is what routing reads.
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (agent) agent, status, produced, state_id
            FROM agent_states
            WHERE correlation_id = %s
            ORDER BY agent, created_at DESC;
            """,
            (correlation_id,),
        )
        rows = cur.fetchall()

    return tuple(
        HistoryEntry(
            agent=agent,
            status=status,
            produced=tuple(
                Ref(kind=str(item.get("kind")), id=str(item.get("id")))
                for item in produced or []),
            state_id=str(state_id),
        )
        for agent, status, produced, state_id in rows
    )
