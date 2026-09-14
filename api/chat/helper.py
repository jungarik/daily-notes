"""Chat section shaping: the caller's clock/locale, and agent results as responses.

The tool-calling loop and citations live in the `agents.conversation` surface;
this helper resolves per-user context and turns the agent's raw result into the
section's response model. Settings and thread state are read via this section's
own db.
"""

from zoneinfo import ZoneInfo

import config
import i18n
from api.chat.schemas import ChatResponse


def normalize_settings(tz_name: str | None, lang: str | None) -> tuple[ZoneInfo, str]:
    tz = config.DEFAULT_TZ
    if tz_name:
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = config.DEFAULT_TZ
    locale = i18n.normalize(lang) or i18n.DEFAULT_LOCALE
    return tz, locale


def turn_response(thread_id: int, result: dict) -> ChatResponse:
    """Shape a finished agent turn into the section's response model."""
    payload_key = "reply" if result["status"] == "answer" else "action"

    return ChatResponse(**{
        "thread_id": thread_id,
        "status": result["status"],
        "citations": result.get("citations") or [],
        payload_key: result[payload_key],
    })


def nothing_to_confirm(thread_id: int) -> ChatResponse:
    """The response for a thread with no action awaiting a decision."""
    return ChatResponse(
        thread_id=thread_id,
        status="answer",
        reply="There's nothing to confirm.",
    )
