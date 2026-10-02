"""Addnote section service: shape the note the editor opens with."""


def editable_note(row: dict) -> dict:
    """The editor's view of a note row.

    A strict pure mapper (api/README): the endpoint does the read and hands the
    row in. It exists for one reason — `text` is nullable in the database and
    the textarea is a controlled React input, where `null` means "uncontrolled"
    and React logs a warning before the field stops tracking its own state. So
    an absent body arrives as the empty string, which is what an empty note
    actually is.
    """
    return {"id": row["id"], "text": row.get("text") or ""}
