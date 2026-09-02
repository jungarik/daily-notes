"""Tool execution result contract."""

from dataclasses import dataclass, field


@dataclass
class ToolResult:
    data: dict
    citations: list[dict] = field(default_factory=list)
    retrieved_chunks: list[dict] = field(default_factory=list)
