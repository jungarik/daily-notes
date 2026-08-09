"""Public API service package.

A separate deployable that fronts the same domain layer the Telegram bot uses
(`note_service`, `search_service`, `reminders`, `links`, ...). Empty for now —
it exposes only health/system endpoints and a private, token-guarded namespace
where the bot's calls will live as they migrate off in-process calls.
"""
