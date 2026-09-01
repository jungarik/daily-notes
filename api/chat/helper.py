"""Chat section service: resolve the caller's clock/locale and run one agent turn.

The tool-calling loop, thread state, and citations live in the shared
`agents.conversation` facade; this helper supplies per-user
context and delegates. Settings are read via this section's own db.
"""

from zoneinfo import ZoneInfo

import config
import i18n
from agents import conversation as chat_agent


def settings(tz_name: str | None, lang: str | None) -> tuple[ZoneInfo, str]:
    tz = config.DEFAULT_TZ
    if tz_name:
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = config.DEFAULT_TZ
    locale = i18n.normalize(lang) or i18n.DEFAULT_LOCALE
    return tz, locale
