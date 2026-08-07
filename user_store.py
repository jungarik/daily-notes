"""Users: surrogate id + optional Telegram chat_id, plus per-user settings."""

from db import cursor


def get_or_create_user(chat_id: int) -> int:
    """Return the internal user id for a Telegram chat, creating it if needed."""
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (chat_id) VALUES (%s)
            ON CONFLICT (chat_id) DO UPDATE SET updated_at = now()
            RETURNING id;
            """,
            (chat_id,),
        )
        return cur.fetchone()[0]


def get_chat_id(user_id: int) -> int | None:
    """Return the Telegram chat_id for a user, or None (e.g. non-Telegram user)."""
    with cursor() as cur:
        cur.execute("SELECT chat_id FROM users WHERE id = %s;", (user_id,))
        row = cur.fetchone()
        return row[0] if row else None


def get_timezone(user_id: int) -> str | None:
    with cursor() as cur:
        cur.execute("SELECT timezone FROM users WHERE id = %s;", (user_id,))
        row = cur.fetchone()
        return row[0] if row else None


def set_timezone(user_id: int, timezone: str) -> None:
    with cursor() as cur:
        cur.execute(
            "UPDATE users SET timezone = %s, updated_at = now() WHERE id = %s;",
            (timezone, user_id),
        )


def get_language(user_id: int) -> str | None:
    with cursor() as cur:
        cur.execute("SELECT language FROM users WHERE id = %s;", (user_id,))
        row = cur.fetchone()
        return row[0] if row else None


def set_language(user_id: int, language: str) -> None:
    with cursor() as cur:
        cur.execute(
            "UPDATE users SET language = %s, updated_at = now() WHERE id = %s;",
            (language, user_id),
        )
