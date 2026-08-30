"""Mapview section — the connections graph (nodes + edges) for the map canvas.

The focus card's note detail is fetched client-side from the notesheet section.
Self-contained vertical: endpoints.py → helper.py → db.py, over shared infra
(db, auth). No imports from `services`/`stores`.
"""
