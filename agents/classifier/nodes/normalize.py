"""normalize node: turn the proposal into canonical metadata.

Deterministic — no model. Fills defaults, canonicalises the path against the
user's localised root folders, and bounds title and tags.

It no longer folds the result into a planner's `tool_call`: inside the enricher
this node ran mid-plan and had to hand its work back to a pending write. The
classifier owns the write itself, so building the action belongs to `agent.py`
and this node's only job is the value. Single public `run`.
"""

from agents.classifier.state import ClassifyState
from common import helper


def run(state: ClassifyState) -> dict:
    context = state.get("context") or {}
    metadata = helper.normalize(
        state.get("raw_metadata") or {},
        state.get("text") or "",
        context.get("root_folders"),
        context.get("default_root"))

    return {
        "metadata": metadata,
        "trace": [*(state.get("trace") or []), {
            "kind": "node",
            "node": "normalize",
            "status": "ok",
        }],
    }
