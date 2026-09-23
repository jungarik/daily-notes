"""The finder agent: the farm's reader.

`SPEC` is the whole public surface — the loop starts it, and nothing else
calls into this package.
"""

from agents.finder.agent import SPEC

__all__ = ["SPEC"]
