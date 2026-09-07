"""Polymorphic specialist lookup, owned by the composition root.

The registry holds the concrete specialist instances; the handoff broker
resolves them by name, so no graph node ever names a specialist itself.
"""

from typing import Protocol


class Specialist(Protocol):
    def plan_action(self, user_id: int, request, now, tz, locale) -> dict | None: ...
    def execute_action(self, user_id: int, action: dict, now, tz, locale) -> str: ...


class SpecialistRegistry:
    def __init__(self):
        self._items: dict[str, Specialist] = {}

    def register(self, name: str, specialist: Specialist) -> None:
        self._items[name] = specialist

    def get(self, name: str) -> Specialist:
        try:
            return self._items[name]
        except KeyError as exc:
            raise LookupError(f"Unknown specialist: {name}") from exc
