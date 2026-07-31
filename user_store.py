"""Per-chat settings (currently just timezone)."""

import os

import psycopg

DATABASE_URL = os.environ["DATABASE_URL"]


def get_timezone(chat_id: int) -> str | None:
    """Return the chat's IANA timezone name, or None if unset."""
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT timezone FROM user_settings WHERE chat_id = %s;", (chat_id,)
        )
        row = cur.fetchone()
        return row[0] if row else None


def set_timezone(chat_id: int, timezone: str) -> None:
    """Upsert the chat's timezone."""
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_settings (chat_id, timezone)
            VALUES (%s, %s)
            ON CONFLICT (chat_id)
            DO UPDATE SET timezone = EXCLUDED.timezone, updated_at = now();
            """,
            (chat_id, timezone),
        )
