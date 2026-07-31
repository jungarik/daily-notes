"""
Reminder persistence (thin CRUD over the reminders table).

Statuses: 'scheduled' (waiting to fire), 'postponed' (snoozed to a new time),
'done' (delivered), 'canceled'. The dispatcher fires rows that are 'scheduled'
or 'postponed' and past due.
"""

import os

import psycopg

DATABASE_URL = os.environ["DATABASE_URL"]

# Statuses that can still fire.
ACTIVE_STATUSES = ("scheduled", "postponed")


def create_reminder(message_id: int, chat_id: int, remind_at, text: str) -> int:
    """Insert a scheduled reminder and return its id."""
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO reminders (message_id, chat_id, remind_at, text)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
            """,
            (message_id, chat_id, remind_at, text),
        )
        return cur.fetchone()[0]


def claim_due_reminders(now, stale_before, limit: int = 50):
    """Atomically claim due reminders for delivery.

    Moves eligible rows to the transient 'sending' status and returns
    [(id, chat_id, text, remind_at)]. `FOR UPDATE SKIP LOCKED` means two
    dispatchers never claim the same row. Rows stuck in 'sending' since before
    `stale_before` (e.g. a crash mid-send) are reclaimed too.
    """
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE reminders SET status = 'sending', updated_at = now()
            WHERE id IN (
                SELECT id FROM reminders
                WHERE (status IN ('scheduled', 'postponed') AND remind_at <= %s)
                   OR (status = 'sending' AND updated_at < %s)
                ORDER BY remind_at
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            RETURNING id, chat_id, text, remind_at;
            """,
            (now, stale_before, limit),
        )
        return cur.fetchall()


def set_status(reminder_id: int, status: str) -> None:
    """Move a reminder to a new status (e.g. 'done', 'canceled')."""
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE reminders SET status = %s, updated_at = now() WHERE id = %s;",
            (status, reminder_id),
        )


def postpone(reminder_id: int, remind_at) -> None:
    """Snooze a reminder to a new time (status → 'postponed')."""
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE reminders
            SET remind_at = %s, status = 'postponed', updated_at = now()
            WHERE id = %s;
            """,
            (remind_at, reminder_id),
        )
