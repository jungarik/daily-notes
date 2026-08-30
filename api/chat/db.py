"""Persistence for the chat section (isolated): the caller's settings.

Chat thread state is the agent's own (in agents/chat); this section only needs
the user's timezone/language to build per-turn context.
"""

from db import cursor


def get_settings(user_id: int) -> tuple[str | None, str | None]:
    """(timezone, language) for a user, (None, None) if absent."""
    with cursor() as cur:
        cur.execute("SELECT timezone, language FROM users WHERE id = %s;", (user_id,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)
