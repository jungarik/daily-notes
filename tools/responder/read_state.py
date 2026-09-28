"""read_state tool: one earlier hop's full working state.

This is how an agent gets more than the turn history gives it. The history
carries statuses and typed refs on purpose — no prose — so an agent that needs
what another actually *did* follows the `state_id` on the entry to here.

**What the allowlist is and is not.** `may_read` comes in on the context, taken
from the calling agent's own `AgentSpec`. It catches an agent reaching for a
state it never declared an interest in — a mistake, a bad merge, a copied
adapter. It is not a defence against an agent that lies about itself, because
every agent here is our own code: an agent passing someone else's name is a
visible edit in its own file, not a runtime input. The tenancy check in `db` is
the guard that does hold unconditionally.
"""

from agents.contracts import ToolResult
from common import helper
from tools.responder import db

WILDCARD = "*"


def may_read(allowed, subject: str) -> bool:
    """Whether a reader holding this allowlist may read a state `subject` wrote."""
    return WILDCARD in (allowed or ()) or subject in (allowed or ())


def invoke(context: dict, args: dict) -> ToolResult:
    error = helper.required_values_error(context, "context", ["user_id"])

    if error:
        return ToolResult({"error": error})

    error = helper.required_values_error(args, "args", ["state_id"])

    if error:
        return ToolResult({"error": error})

    saved = db.get_state(str(args["state_id"]), context["user_id"])

    if saved is None:
        return ToolResult({"error": "Error: state not found."})

    if not may_read(context.get("may_read"), saved["agent"]):
        # Says which agent was refused, never what the row held.
        return ToolResult({
            "error": "Error: not allowed to read %s state." % saved["agent"],
        })

    return ToolResult(saved)
