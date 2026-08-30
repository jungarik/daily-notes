"""Header section service: assemble the three top-bar counts."""

from api.header import db


def stats(user_id: int) -> dict:
    """{notes, links, reminders} — the header's Instagram-style stat trio."""
    return {
        "notes": db.count_notes(user_id),
        "links": db.count_links(user_id),
        "reminders": db.count_active_reminders(user_id),
    }
