"""Addnote section — the Add note page's own reads and (later) writes.

Self-contained vertical: endpoints.py → helper.py → db.py, with schemas.py for
the edge models. It owns its SQL and imports only shared infra, like every
other section; nothing here is reached from another vertical.

Today it serves one method: `GET /api/addnote/{note_id}`, the note a tapped
Edit is about to show. The page has no create or update endpoint yet — its
tick and capture buttons are deliberately disabled — so this is a read-only
section for now, and the folder exists so the save lands beside the read
rather than in whichever vertical happened to be open.
"""
