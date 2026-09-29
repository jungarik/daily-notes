"""Persistence for the header section (isolated): the vault's root-folder counts.

The section owns its own SQL, including the language lookup — reaching into
another vertical for it would be the coupling the layout rules exist to prevent.
"""

from db import cursor


def get_language(user_id: int) -> str | None:
    """The user's chosen language, or None when they have never set one.

    Only the bot writes this column, so a Mini-App-only user has NULL here and
    the caller decides what that means.
    """
    with cursor() as cur:
        cur.execute("SELECT language FROM users WHERE id = %s;", (user_id,))
        row = cur.fetchone()

    return row[0] if row else None


def count_root_entries(user_id: int, root_names: list[str]) -> dict[str, int]:
    """Per root folder, how many rows an explorer would show inside it.

    That is each distinct sub-folder once, plus each note filed at the root with
    no sub-folder of its own — so `Projects/Home`, `Projects/Work` and two loose
    notes in `Projects` come to four.

    Paths are capped at two levels (`common.helper.clean_path`), so splitting on
    the first slash is exhaustive rather than a simplification. Roots with
    nothing in them do not come back at all; the caller defaults them to zero.

    Matching is by the *stored* name, which is localised: a vault written in one
    language and read in another will not match. That is a deliberate choice at
    the caller, not an oversight here.
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT root,
                   count(DISTINCT sub) FILTER (WHERE sub <> '')
                 + count(*)            FILTER (WHERE sub =  '') AS entries
            FROM (
                SELECT split_part(path, '/', 1) AS root,
                       split_part(path, '/', 2) AS sub
                FROM notes
                WHERE user_id = %s AND path IS NOT NULL AND path <> ''
            ) parts
            WHERE root = ANY(%s)
            GROUP BY root;
            """,
            (user_id, root_names),
        )

        return {row[0]: row[1] for row in cur.fetchall()}
