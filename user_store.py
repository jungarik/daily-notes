"""Per-chat settings (timezone, language)."""

from db import cursor


def get_timezone(chat_id: int) -> str | None:
    """Return the chat's IANA timezone name, or None if unset."""
    with cursor() as cur:
        cur.execute(
            "SELECT timezone FROM user_settings WHERE chat_id = %s;", (chat_id,)
        )
        row = cur.fetchone()
        return row[0] if row else None


def set_timezone(chat_id: int, timezone: str) -> None:
    """Upsert the chat's timezone (leaves language untouched)."""
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_settings (chat_id, timezone)
            VALUES (%s, %s)
            ON CONFLICT (chat_id)
            DO UPDATE SET timezone = EXCLUDED.timezone, updated_at = now();
            """,
            (chat_id, timezone),
        )


def get_language(chat_id: int) -> str | None:
    """Return the chat's language code, or None if unset."""
    with cursor() as cur:
        cur.execute(
            "SELECT language FROM user_settings WHERE chat_id = %s;", (chat_id,)
        )
        row = cur.fetchone()
        return row[0] if row else None


def set_language(chat_id: int, language: str) -> None:
    """Upsert the chat's language (leaves timezone untouched)."""
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_settings (chat_id, language)
            VALUES (%s, %s)
            ON CONFLICT (chat_id)
            DO UPDATE SET language = EXCLUDED.language, updated_at = now();
            """,
            (chat_id, language),
        )
