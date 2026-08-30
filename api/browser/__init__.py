"""Browser section — the note list backing the folder tree (and the client-side
search/header derivations that read the same loaded notes).

Self-contained vertical: endpoints.py → helper.py → db.py, over shared infra
(db, auth). No imports from `services`/`stores`.
"""
