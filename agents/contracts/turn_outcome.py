"""What one call into the loop gives back to the endpoint."""

from dataclasses import dataclass

from agents.contracts.history_entry import HistoryEntry


@dataclass(frozen=True)
class TurnOutcome:
    """What one call into the loop gives back to the endpoint.

    `pending` is set only on `needs_input`: it is what the calling section stores
    so a later confirm can find this turn again.
    """

    status: str
    correlation_id: str
    history: tuple[HistoryEntry, ...]
    pending: dict | None = None
    reply: str | None = None
