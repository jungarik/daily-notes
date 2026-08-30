"""Feed section — full note cards for the web-app feed (newest first).

Self-contained vertical: endpoints.py (router) → helper.py (shaping) →
store.py (SQL). Shared infra only (db, auth deps, media_token); no imports from
`services`/`stores`.
"""
