"""State for the reminder planning graph.

`events` carries the turn's node timeline. It is the one accumulating channel,
so it declares a reducer: a node returns only the events it produced and
LangGraph appends them. Every other channel takes the default reducer, which
replaces — which is what those fields want.
"""

from datetime import datetime
from typing import Annotated, TypedDict

from agents.runtime.events import append


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


