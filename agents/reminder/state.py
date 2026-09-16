"""State for the reminder planning graph.

`events` carries the turn's node timeline. It is the one accumulating channel,
so it declares a reducer: a node returns only the events it produced and
LangGraph appends them. Every other channel takes the default reducer, which
replaces — which is what those fields want.
"""

from datetime import datetime
from typing import Annotated, TypedDict

from agents.runtime.events import append


class Ctx:
    """User-scoped clock and locale for one reminder turn."""

    def __init__(self, user_id: int, now, tz=None, locale: str = "en"):
        self.user_id = user_id
        self.now = now
        self.tz = tz
        self.locale = locale


class ReminderPlanUpdate(TypedDict, total=False):
    locale: str | None
    extracted_time: dict
    action: dict | None
    events: Annotated[list[dict], append]


class ReminderPlanState(ReminderPlanUpdate):
    contract: dict
    now: datetime


class ReminderPlanOutput(TypedDict):
    """What the planning graph promises its caller: the write it produced (or
    none), and the events explaining how it got there."""

    action: dict | None
    events: list[dict]


def context_to_dict(ctx: Ctx) -> dict:
    return {
        "user_id": ctx.user_id,
        "now": ctx.now.isoformat() if hasattr(ctx.now, "isoformat") else ctx.now,
        "tz": str(ctx.tz) if ctx.tz is not None else None,
        "locale": ctx.locale,
    }
