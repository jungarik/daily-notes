"""
Link candidate suggestions: which notes to connect a note to.

Semantic nearest neighbours, re-ranked with metadata signals (shared path/tags),
so the human is offered the most obviously-related notes first. The user picks
from the list; nothing is linked automatically.
"""

import note_store
import chunk_store
import semantic

PATH_BOOST = 0.10   # same/adjacent folder
TAG_BOOST = 0.05    # per shared tag


def _same_family(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def candidates(user_id: int, note_id: int, limit: int = 5) -> list[dict]:
    """Ranked link candidates for a note: [{note_id, title, path, tags, score}].

    Includes already-linked notes (the picker marks them ✅); only the note
    itself is excluded.
    """
    note = note_store.get_note(note_id)
    if not note:
        return []

    embedding = semantic.embed(note["text"])
    rows = chunk_store.candidate_notes(user_id, embedding, [note_id], limit * 3)

    note_path = note["path"]
    note_tags = set(note["tags"] or [])

    def score(r: dict) -> float:
        s = 1.0 - float(r["distance"])  # cosine similarity
        if _same_family(note_path, r["path"]):
            s += PATH_BOOST
        s += TAG_BOOST * len(note_tags & set(r["tags"] or []))
        return s

    for r in rows:
        r["score"] = round(score(r), 4)
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:limit]
