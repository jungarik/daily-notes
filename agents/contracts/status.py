"""The three ways a hop can end.

Its own module because `AgentResult` and `HistoryEntry` both use it and neither
owns it: the status is a property of the hop, not of either shape.
"""

from typing import Literal

Status = Literal["done", "needs_input", "failed"]
