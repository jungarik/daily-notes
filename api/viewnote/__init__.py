"""Viewnote section — the View note page's own reads.

A copy of the `addnote` vertical's reads, kept as its own section on purpose:
this codebase duplicates a section's SQL and shaping rather than sharing it, so
the viewer can grow in its own direction without a change here rippling into the
editor, or the other way round. Self-contained: endpoints.py → helper.py →
db.py, with schemas.py for the edge models, importing only shared infra.

It serves reads only — `GET /api/viewnote/{note_id}` and the two rosters the
page's path wheels offer. There is no create or update endpoint: the page that
uses them cannot save yet, and when it can, the write belongs here beside the
read rather than in whichever vertical happened to be open.
"""
