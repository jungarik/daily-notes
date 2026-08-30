"""Notesheet section — one note's full detail for the preview sheet (also used
by the map's focus card and the chat citation chips, client-side).

Self-contained vertical: endpoints.py → helper.py → db.py, over shared infra
(db, auth, media_token). No imports from `services`/`stores`.
"""
