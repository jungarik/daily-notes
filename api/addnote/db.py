"""Persistence for the addnote section (isolated): the note being edited."""

from psycopg.types.json import Json

from db import cursor


def note_for_user(user_id: int, note_id: int) -> dict | None:
    """The note's editable body, owner-scoped, or None.

    The `user_id` predicate is the tenancy guard, not a convenience: without it
    any authenticated caller could read any note by guessing an id. It is in
    the query rather than a check afterwards so there is no path that forgets
    it.

    `path` and `tags` ride along with the body because they belong to the same
    row — a second query for two columns of the row already in hand would be a
    query for nothing.
    """
    with cursor() as cur:
        cur.execute(
            "SELECT id, text, path, tags FROM notes WHERE id = %s AND user_id = %s;",
            (note_id, user_id),
        )
        row = cur.fetchone()

        return ({"id": row[0], "text": row[1], "path": row[2], "tags": row[3]}
                if row else None)


def attachments(note_id: int) -> list[dict]:
    """The note's attachments in carousel order: [{id, kind, mime}].

    No owner predicate and none needed: the caller has already established
    ownership of the note, and `note_id` is not user input by the time it gets
    here. `position, id` is the same order the feed and the card use, so the
    editor's first photo is the one the user saw first.

    The storage key is not selected. Nothing client-facing may carry it — the
    bucket is private and the signed proxy URL is the only way in.
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, kind, mime FROM note_attachments
            WHERE note_id = %s ORDER BY position, id;
            """,
            (note_id,),
        )
        return [{"id": r[0], "kind": r[1], "mime": r[2]} for r in cur.fetchall()]


def linked_note_ids(user_id: int, note_id: int) -> list[int]:
    """Every note this one is connected to, in either direction.

    Links are directed and backlinks are the reverse query, so a note's
    neighbours are the union of both — the same set the card's chips show. The
    `user_id` predicate is on the *other* endpoint: a link whose far side
    belongs to someone else must not leak that note's id, and the rows are
    reachable because this note's owner wrote the edge.

    Returned as a sorted list rather than a set so the response is stable: an
    unordered payload makes a diff between two reads unreadable.
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT l.to_note_id FROM note_links l
            JOIN notes n ON n.id = l.to_note_id AND n.user_id = %s
            WHERE l.from_note_id = %s
            UNION
            SELECT l.from_note_id FROM note_links l
            JOIN notes n ON n.id = l.from_note_id AND n.user_id = %s
            WHERE l.to_note_id = %s;
            """,
            (user_id, note_id, user_id, note_id),
        )
        return sorted(row[0] for row in cur.fetchall())


def get_language(user_id: int) -> str | None:
    """The user's chosen language, or None when they have never set one.

    Duplicated from the other verticals on purpose — this section owns its SQL.
    Only the bot writes this column, so a Mini-App-only user has NULL here and
    the caller resolves the default.
    """
    with cursor() as cur:
        cur.execute("SELECT language FROM users WHERE id = %s;", (user_id,))
        row = cur.fetchone()

        return row[0] if row else None


def list_paths(user_id: int) -> list[str]:
    """Every distinct path the user has filed a note under, alphabetically.

    The same read the contextmenu section makes, duplicated rather than
    imported: a section owns its SQL, so the editor's picker cannot break
    because the ⋮ menu's changed. Ordering into root groups is the caller's
    job — this returns a stable list, not a presentation.
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT path FROM notes
            WHERE user_id = %s AND path IS NOT NULL AND path <> ''
            ORDER BY path;
            """,
            (user_id,),
        )
        return [row[0] for row in cur.fetchall()]


def create_note(user_id: int, text: str, path: str, tags: list[str]) -> int:
    """Insert a note written in the editor and return its id.

    `title` is left NULL on purpose. It is the enrichment agent's field — an
    LLM's one-line summary — and a title the user never wrote would be a
    guess presented as theirs. Every section that displays a note already
    falls back to a text snippet when it is absent (`_display_title` in feed,
    explorer, notesheet, mapview and search), so an untitled note reads as its
    own first words everywhere.

    `source_type` is 'text': this is typed, like the bot's text capture, and
    the voice/photo kinds have no editor yet.
    """
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO notes (user_id, text, source_type, path, tags)
            VALUES (%s, %s, 'text', %s, %s) RETURNING id;
            """,
            (user_id, text, path, Json(tags)),
        )
        return cur.fetchone()[0]


def update_note(user_id: int, note_id: int, text: str, path: str,
                tags: list[str]) -> bool:
    """Owner-scoped update of the three fields the editor owns. True if a row
    went.

    The `user_id` predicate is the tenancy guard, in the statement rather than
    a check before it, so no path can forget it. Nothing else on the row is
    touched: `title`, `note_type` and `priority` belong to enrichment, and
    blanking them here would undo work the user asked an agent for.
    """
    with cursor() as cur:
        cur.execute(
            """
            UPDATE notes SET text = %s, path = %s, tags = %s
            WHERE id = %s AND user_id = %s RETURNING id;
            """,
            (text, path, Json(tags), note_id, user_id),
        )
        return cur.fetchone() is not None


def replace_chunks(note_id: int, chunks: list[dict]) -> None:
    """Swap the note's embedded chunks for a freshly built set, in one
    transaction.

    One `cursor()` for both statements is the point: a delete that commits
    without its insert leaves the note invisible to search and RAG, which is
    worse than leaving the old chunks in place. The caller builds the chunks
    *before* calling this, so the embedding round trip cannot fail between the
    two.
    """
    with cursor() as cur:
        cur.execute("DELETE FROM note_chunks WHERE note_id = %s;", (note_id,))

        for chunk in chunks:
            cur.execute(
                """
                INSERT INTO note_chunks
                    (note_id, chunk_index, content, token_count, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s, %s::vector);
                """,
                (note_id, chunk["index"], chunk["content"], chunk["token_count"],
                 Json(chunk["metadata"]), chunk["embedding"]),
            )
