"""Persistence for the search section (isolated): substring match over notes."""

from db import cursor


def search_notes(user_id: int, query: str, limit: int = 50) -> list[dict]:
    """Notes whose title, path or text contains `query` (case-insensitive),
    newest first: [{id, path, text}].

    The `title` column is still *matched* even though it is never shown: an
    enriched title often holds a word the note itself does not, and dropping it
    from the predicate would make those notes unfindable. The consequence is
    worth knowing — a hit can match on text the row does not display.
    """
    like = "%" + query.replace("%", r"\%").replace("_", r"\_") + "%"
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, path, text
            FROM notes
            -- An un-filed note (no path) is not part of the vault yet: it is
            -- hidden from every browsing view until enrichment gives it a
            -- home. The bot and the chat agents still see it, so it stays
            -- recoverable. Duplicated per section, like the rest of the SQL.
            WHERE user_id = %s AND path IS NOT NULL AND path <> ''
              AND (coalesce(title, '') ILIKE %s
                   OR coalesce(path, '') ILIKE %s
                   OR coalesce(text, '') ILIKE %s)
            ORDER BY created_at DESC NULLS LAST, id DESC
            LIMIT %s;
            """,
            (user_id, like, like, like, limit),
        )
        return [
            {"id": r[0], "path": r[1], "text": r[2]}
            for r in cur.fetchall()
        ]
