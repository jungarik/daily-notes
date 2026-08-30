"""Persistence for the search section (isolated): substring match over notes."""

from db import cursor


def search_notes(user_id: int, query: str, limit: int = 50) -> list[dict]:
    """Notes whose title, path, or text contains `query` (case-insensitive),
    newest first: [{id, title, path, text}]."""
    like = "%" + query.replace("%", r"\%").replace("_", r"\_") + "%"
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, title, path, text
            FROM notes
            WHERE user_id = %s
              AND (coalesce(title, '') ILIKE %s
                   OR coalesce(path, '') ILIKE %s
                   OR coalesce(text, '') ILIKE %s)
            ORDER BY created_at DESC NULLS LAST, id DESC
            LIMIT %s;
            """,
            (user_id, like, like, like, limit),
        )
        return [
            {"id": r[0], "title": r[1], "path": r[2], "text": r[3]}
            for r in cur.fetchall()
        ]
