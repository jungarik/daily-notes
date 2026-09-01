from typing import TypedDict


class TraceEvent(TypedDict, total=False):
    name: str
    route: str
    args: dict
    result: str
