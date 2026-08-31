"""Chat section service: resolve the caller's clock/locale and run one agent turn.

The tool-calling loop, thread state, and citations live in the shared
`agents.chat` engine (itself self-contained); this helper supplies per-user
context and delegates. Settings are read via this section's own db.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import config
import i18n
from agents import chat as chat_agent
from api.chat import db


def _settings(user_id: int) -> tuple[ZoneInfo, str]:
    tz_name, lang = db.get_settings(user_id)
    tz = config.DEFAULT_TZ
    if tz_name:
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = config.DEFAULT_TZ
    locale = i18n.normalize(lang) or i18n.DEFAULT_LOCALE
    return tz, locale


def run_turn(user_id: int, message: str, thread_id: int | None) -> dict:
    """One user message → {thread_id, status, reply|action, citations}."""
    tz, locale = _settings(user_id)
    return chat_agent.start_turn(user_id, message, thread_id, datetime.now(tz), tz, locale)


def confirm_turn(user_id: int, thread_id: int, approve: bool) -> dict:
    """Approve/decline the handed-off action, then continue the turn."""
    tz, locale = _settings(user_id)
    return chat_agent.confirm(user_id, thread_id, approve, datetime.now(tz), tz, locale)
