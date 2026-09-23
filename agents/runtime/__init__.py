"""The machinery that runs a turn, shared by every agent.

Not "services without domain decisions" — `broker.py` decides how a turn
ends, and `registry.py` is the roster it decides over. What unites this
package is that none of it is *one agent's* work: the turn loop, the roster,
the turn tree (`state_store`), at-most-once writes (`execution_ledger`),
entering a compiled graph (`loop`), its checkpoints, the model gateway, and
the tool adapter.

Who runs next is not here — that is `agents/router/`. The shapes everything
passes around are not here either — that is `agents/contracts/`, which
imports nothing.
"""
