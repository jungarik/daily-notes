"""SQL for the loop's cross-agent tools."""

from db import cursor


def get_state(state_id: str, user_id: int) -> dict | None:
    """One saved hop, scoped to its owner.

    The owner check is not the allowlist — it is the same tenancy guard every
    other tool applies, so a state id from one user's turn can never read
    another's row however the allowlist is configured.
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT agent, status, state
            FROM agent_states
            WHERE state_id = %s AND user_id = %s;
            """,
            (state_id, user_id),
        )
        row = cur.fetchone()

    if row is None:
        return None

    return {"agent": row[0], "status": row[1], "state": row[2]}
