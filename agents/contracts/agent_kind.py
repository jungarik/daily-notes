"""The one `Ref.kind` the loop itself reads.

Every other kind is an agent's own word for what it made, and the loop never
looks at the value (see `ref.py`). This one is the exception, and it exists
because the router answers in `produced` like any other agent: a
`Ref(AGENT_KIND, "<name>")` is how a routing decision reaches the loop.

It lives here rather than in either module because the loop and the router may
not import each other — that separation is what lets a routing rule change
without touching the loop. A shared literal in two files would drift silently
and break routing; a contract cannot.
"""

AGENT_KIND = "agent"
