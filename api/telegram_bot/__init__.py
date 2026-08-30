"""Telegram-bot section — every endpoint the bot calls (capture, enrich,
atomize, polish, delete, links, reminders + dispatcher, user identity/settings,
RAG search, ping), all under /api/telegram_bot.

Unlike the web-app sections, the bot drives the shared note lifecycle (capture,
enrichment, reminder detection, RAG) — genuinely shared domain that also backs
the future web-capture path — so this section orchestrates `common` rather than
duplicating that logic. endpoints.py → helper.py → common; store.py notes where
persistence lives.
"""
