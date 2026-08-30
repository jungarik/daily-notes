"""Telegram-bot section — every endpoint the bot calls (capture, enrich,
atomize, polish, delete, links, reminders + dispatcher, user identity/settings,
RAG search, ping), all under /api/telegram_bot.

Self-contained like every other vertical: endpoints.py (router) → helper.py
(the full note-lifecycle domain: capture, one-shot enrichment, reminders, links,
user settings, RAG) → db.py (its SQL). Shared infra only (config, i18n,
openai_client, file_store, api.deps); no shared domain layer.
"""
