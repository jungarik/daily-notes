"""A typed pointer to something an agent made."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Ref:
    """A typed pointer to something an agent made.

    `kind` is the agent's own word for it ("note", "reminder", "link"). The
    loop checks that it is a non-empty string sitting next to an id and,
    with one exception, never reads the value — so the farm needs no shared
    domain vocabulary.

    The exception is `AGENT_KIND`: the router answers in `produced` like
    every other agent, so `Ref("agent", "<name>")` is how its decision
    reaches the loop. That is the whole of the reserved vocabulary, and it
    names an agent rather than anything in the user's domain.
    """

    kind: str
    id: str
