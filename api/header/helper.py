"""Header section service: assemble the three top-bar counts."""

from api.header import store


def stats(user_id: int) -> dict:
    """{notes, links, reminders} — the header's Instagram-style stat trio."""
    return {
        "notes": store.count_notes(user_id),
        "links": store.count_links(user_id),
        "reminders": store.count_active_reminders(user_id),
    }
