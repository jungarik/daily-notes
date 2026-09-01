from typing import TypedDict


class ExecutionResult(TypedDict, total=False):
    ok: bool
    content: str
    error: str
