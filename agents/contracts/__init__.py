"""Stable data contracts shared by agent boundaries."""

from agents.contracts.execution import ExecutionResult
from agents.contracts.handoff import HandoffContract
from agents.contracts.proposal import ActionProposal, CaptureProposal, RelatedNote
from agents.contracts.tool_result import ToolResult
from agents.contracts.trace import TraceEvent

__all__ = [
    "ActionProposal", "CaptureProposal", "RelatedNote", "ExecutionResult",
    "HandoffContract", "ToolResult", "TraceEvent",
]
