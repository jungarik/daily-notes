"""
Reminder persistence (thin CRUD over the reminders table).

Statuses: 'scheduled' (waiting to fire), 'postponed' (snoozed to a new time),
'done' (delivered), 'canceled'. The dispatcher fires rows that are 'scheduled'
or 'postponed' and past due.
"""

from db import cursor

# Statuses that can still fire.
ACTIVE_STATUSES = ("scheduled", "postponed")


def create_reminder(message_id: int, chat_id: int, remind_at) -> int:
    """Insert a scheduled reminder and return its id.

    The reminder's text is the message it was parsed from (joined via
    message_id at read time), so it isn't stored on the reminder row.
    """
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO reminders (message_id, chat_id, remind_at)
            VALUES (%s, %s, %s)
            RETURNING id;
            """,
            (message_id, chat_id, remind_at),
        )
        return cur.fetchone()[0]


def claim_due_reminders(now, stale_before, limit: int = 50):
    """Atomically claim due reminders for delivery.

    Moves eligible rows to the transient 'sending' status and returns
    [(id, chat_id, text, remind_at)] (text joined from messages).
    `FOR UPDATE SKIP LOCKED` means two dispatchers never claim the same row.
    Rows stuck in 'sending' since before `stale_before` (crash mid-send) are
    reclaimed too.
    """
    with cursor() as cur:
        cur.execute(
            """
            WITH claimed AS (
                UPDATE reminders SET status = 'sending', updated_at = now()
                WHERE id IN (
                    SELECT id FROM reminders
                    WHERE (status IN ('scheduled', 'postponed') AND remind_at <= %s)
                       OR (status = 'sending' AND updated_at < %s)
                    ORDER BY remind_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                )
                RETURNING id, chat_id, message_id, remind_at
            )
            SELECT c.id, c.chat_id, m.text, c.remind_at
            FROM claimed c
            JOIN messages m ON m.id = c.message_id
            ORDER BY c.remind_at;
            """,
            (now, stale_before, limit),
        )
        return cur.fetchall()


def upcoming_reminders(chat_id: int, limit: int = 10):
    """Return [(id, remind_at, text, status)] of a chat's active reminders."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT r.id, r.remind_at, m.text, r.status
            FROM reminders r
            JOIN messages m ON m.id = r.message_id
            WHERE r.chat_id = %s AND r.status IN ('scheduled', 'postponed')
            ORDER BY r.remind_at
            LIMIT %s;
            """,
            (chat_id, limit),
        )
        return cur.fetchall()


def count_active(chat_id: int) -> int:
    """Count a chat's active (scheduled/postponed) reminders."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM reminders
            WHERE chat_id = %s AND status IN ('scheduled', 'postponed');
            """,
            (chat_id,),
        )
        return cur.fetchone()[0]


def set_status(reminder_id: int, status: str) -> None:
    """Move a reminder to a new status (e.g. 'done', 'canceled')."""
    with cursor() as cur:
        cur.execute(
            "UPDATE reminders SET status = %s, updated_at = now() WHERE id = %s;",
            (status, reminder_id),
        )


def postpone(reminder_id: int, remind_at) -> None:
    """Snooze a reminder to a new time (status → 'postponed')."""
    with cursor() as cur:
        cur.execute(
            """
            UPDATE reminders
            SET remind_at = %s, status = 'postponed', updated_at = now()
            WHERE id = %s;
            """,
            (remind_at, reminder_id),
        )
