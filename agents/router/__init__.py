"""The router agent: which agent takes the next hop.

`SPEC` is the whole public surface, as for every other agent — the loop reaches
it through the registry by name, never by importing this package.
"""

from agents.router.agent import SPEC

__all__ = ["SPEC"]
