"""Persistence for note links (directed; backlinks are the reverse query)."""

from db import cursor


def add_link(from_note_id: int, to_note_id: int) -> None:
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO note_links (from_note_id, to_note_id)
            VALUES (%s, %s)
            ON CONFLICT (from_note_id, to_note_id) DO NOTHING;
            """,
            (from_note_id, to_note_id),
        )


def remove_link(from_note_id: int, to_note_id: int) -> None:
    with cursor() as cur:
        cur.execute(
            "DELETE FROM note_links WHERE from_note_id = %s AND to_note_id = %s;",
            (from_note_id, to_note_id),
        )


def is_linked(from_note_id: int, to_note_id: int) -> bool:
    with cursor() as cur:
        cur.execute(
            "SELECT 1 FROM note_links WHERE from_note_id = %s AND to_note_id = %s;",
            (from_note_id, to_note_id),
        )
        return cur.fetchone() is not None


def links_of(note_id: int):
    """All connected notes (both directions) as [(note_id, title, path, direction)].

    direction is 'out' (this note → other) or 'in' (other → this note, a backlink).
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT n.id, n.title, n.path, 'out' AS direction
            FROM note_links l JOIN notes n ON n.id = l.to_note_id
            WHERE l.from_note_id = %s
            UNION
            SELECT n.id, n.title, n.path, 'in' AS direction
            FROM note_links l JOIN notes n ON n.id = l.from_note_id
            WHERE l.to_note_id = %s;
            """,
            (note_id, note_id),
        )
        return cur.fetchall()


def links_of_for_user(user_id: int, note_id: int, limit: int = 100):
    """Direct neighbours of a note (depth 1 only), owner-scoped, for the web-app
    preview. Returns [(id, title, text, direction)] where direction is 'out'
    (a link) or 'in' (a backlink).

    This is a single, non-recursive query over immediate neighbours — it never
    traverses the graph, so link cycles are harmless and there's no recursion.
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT n.id, n.title, n.text, 'out' AS direction
            FROM note_links l JOIN notes n ON n.id = l.to_note_id
            WHERE l.from_note_id = %s AND n.user_id = %s
            UNION
            SELECT n.id, n.title, n.text, 'in' AS direction
            FROM note_links l JOIN notes n ON n.id = l.from_note_id
            WHERE l.to_note_id = %s AND n.user_id = %s
            ORDER BY direction
            LIMIT %s;
            """,
            (note_id, user_id, note_id, user_id, limit),
        )
        return cur.fetchall()
