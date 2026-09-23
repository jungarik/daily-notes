"""Chat v2 shaping: the caller's clock/locale, and turn outcomes as responses.

The broker runs the turn; this helper resolves per-user context, keeps the
thread transcript, and turns a `TurnOutcome` into the section's response model.

Two differences from v1 are worth naming, because both move work *into* this
file. The broker returns no message list — the finder builds its own scratch
messages and keeps them — so the transcript is appended here, which leaves the
thread a clean record of what the user and the assistant said. And the turn's
outcome is a status plus a reply rather than a graph state, so the mapping onto
`answer` / `confirm` is a small pure function rather than a key lookup.
"""

from zoneinfo import ZoneInfo

import config
import i18n
from api.chat_v2.schemas import ChatAction, ChatResponse

NOTHING_TO_CONFIRM = "There's nothing to confirm."

# The turn ran but no agent wrote a reply. The responder makes this rare — it
# cannot fail — so this is a real fault, not a resting state.
NO_REPLY = "Something went wrong and I couldn't answer that. Please try again."


def normalize_settings(tz_name: str | None, lang: str | None) -> tuple[ZoneInfo, str]:
    tz = config.DEFAULT_TZ

    if tz_name:
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = config.DEFAULT_TZ

    locale = i18n.normalize(lang) or i18n.DEFAULT_LOCALE

    return tz, locale


def build_context(user_id: int, now, tz: ZoneInfo, locale: str) -> dict:
    """The `UserContext` every agent on the turn is given."""
    return {
        "user_id": user_id,
        "now": now.isoformat(),
        "tz": str(tz),
        "locale": locale,
    }


def find_resumable(pending: dict | None) -> dict | None:
    """The stored `pending` if this version can resume it, else None.

    v1 and v2 share the `chat_threads` row but not the shape they put in it:
    v1 stores a handed-off action, v2 stores the broker's turn handle. A
    `correlation_id` is what identifies the latter, so a thread the other
    version left mid-confirm is reported as nothing to confirm rather than
    crashing on a key that was never there.
    """
    return pending if pending and pending.get("correlation_id") else None


def find_last_user_message(messages: list[dict]) -> str:
    """What the user asked, for a confirm to carry back into the turn.

    A confirm is a decision, not an instruction, but the hops it resumes — and
    the responder writing the second reply — still need the request that started
    the turn to phrase anything about it.
    """
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("content") or ""

    return ""


def append_turn(messages: list[dict], message: str | None, reply: str | None) -> list[dict]:
    """The transcript with this turn folded in.

    A new list, never an edit of the one that was loaded. A confirm passes
    `message=None`: it adds the assistant's second reply without repeating the
    user's original request.
    """
    appended = list(messages)

    if message:
        appended.append({"role": "user", "content": message})

    if reply:
        appended.append({"role": "assistant", "content": reply})

    return appended


def build_action(ask: dict) -> ChatAction:
    """The proposed write, as the client renders it."""
    action = ask.get("action") or {}

    return ChatAction(
        name=action.get("name") or "",
        args=action.get("args") or {},
        summary=ask.get("summary") or action.get("summary") or "",
        kind=ask.get("kind") or "confirm")


def turn_response(thread_id: int, status: str, reply: str | None,
                  pending: dict | None) -> ChatResponse:
    """Shape a finished turn into the section's response model.

    It takes the three fields it reads rather than the whole `TurnOutcome`, so
    it stays a pure mapping with nothing to know about the broker's contract.
    """
    if status == "needs_input":
        return ChatResponse(
            thread_id=thread_id,
            status="confirm",
            action=build_action((pending or {}).get("ask") or {}))

    return ChatResponse(thread_id=thread_id, status="answer", reply=reply or NO_REPLY)


def nothing_to_confirm(thread_id: int) -> ChatResponse:
    """The response for a thread with no action awaiting a decision."""
    return ChatResponse(thread_id=thread_id, status="answer", reply=NOTHING_TO_CONFIRM)
