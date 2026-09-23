"""A typed pointer to something an agent made."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Ref:
    """A typed pointer to something an agent made.

    `kind` is the agent's own word for it ("note", "reminder", "link"). The
    broker checks that it is a non-empty string sitting next to an id and never
    reads the value, so the farm needs no shared domain vocabulary.
    """

    kind: str
    id: str
