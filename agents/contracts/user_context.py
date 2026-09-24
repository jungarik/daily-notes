"""Who a turn belongs to, and the clock to resolve it against."""

from datetime import datetime
from typing import TypedDict
from zoneinfo import ZoneInfo


class UserContext(TypedDict, total=False):
    """Who the turn belongs to, and the clock to resolve it against.

    Plain JSON by design: `now` and `tz` travel as strings so the envelope stays
    serialisable, and each agent restores them against its own clock. A confirm
    arriving ten minutes later carries a *different* context, which is the point.

    `user_id` is the one key an agent can count on — it is the turn's owner, and
    the only place that owner is written down. Everything else is optional, so an
    agent reading a key it was not given falls back rather than failing.

    Every key is optional to the type checker (`total=False`), so `user_id` is
    enforced at runtime instead: the loop subscripts it, and a context without
    one raises rather than writing a row for nobody.
    """

    user_id: int
    now: str
    tz: str | None
    locale: str


def build_context(user_id: int, now, tz=None, locale: str = "en") -> UserContext:
    """One context, as the JSON it travels and persists as.

    A missing timezone stays `None` rather than becoming `str(None)` — the
    round trip has to survive a caller that never had one, and a tool handed
    the literal string "None" where it expects a tzinfo fails much later.
    """
    return {
        "user_id": user_id,
        "now": now.isoformat() if hasattr(now, "isoformat") else now,
        "tz": str(tz) if tz is not None else None,
        "locale": locale,
    }


def restore_clock(context: UserContext) -> tuple:
    """`(now, tz, locale)` as live values, from the context's plain JSON.

    Every agent had its own copy of this and they had drifted — one accepted a
    `tz` that was not a string, another did not. It lives beside the type it
    reads because that is the only thing it knows about; it does no I/O and
    imports nothing but the standard library, so it stays at the bottom of the
    dependency graph like the rest of this package.

    Forgiving by design: a context is replayed from a row written by older code
    or by a client, and an unparseable clock is worth degrading over rather
    than losing the turn for.
    """
    raw_now = context.get("now")
    raw_tz = context.get("tz")

    return (
        datetime.fromisoformat(raw_now) if isinstance(raw_now, str) else raw_now,
        ZoneInfo(raw_tz) if isinstance(raw_tz, str) and raw_tz else None,
        context.get("locale") or "en",
    )
