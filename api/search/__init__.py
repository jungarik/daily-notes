"""Search section — server-side text search over the user's notes (title / path /
text), backing the web-app search tab.

Self-contained vertical: endpoints.py → helper.py → store.py, over shared infra
(db, auth). No imports from `services`/`stores`. (The bot's semantic RAG search is
a separate concern and lives in the telegram_bot section.)
"""
