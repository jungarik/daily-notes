"""Persistence for the header section (isolated): the three top-bar counts."""

from db import cursor


def count_notes(user_id: int) -> int:
    """How many notes the user has."""
    with cursor() as cur:
        cur.execute("SELECT count(*) FROM notes WHERE user_id = %s;", (user_id,))
        return cur.fetchone()[0]


def count_links(user_id: int) -> int:
    """How many links (edges) in the user's vault — both endpoints must be theirs."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT count(*)
            FROM note_links l
            JOIN notes a ON a.id = l.from_note_id AND a.user_id = %s
            JOIN notes b ON b.id = l.to_note_id AND b.user_id = %s;
            """,
            (user_id, user_id),
        )
        return cur.fetchone()[0]


def count_active_reminders(user_id: int) -> int:
    """How many active (scheduled/postponed) reminders the user has."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM reminders
            WHERE user_id = %s AND status IN ('scheduled', 'postponed');
            """,
            (user_id,),
        )
        return cur.fetchone()[0]
