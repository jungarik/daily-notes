"""classify_normalize node: normalize the proposal into canonical metadata.

Deterministic — no LLM. Fills defaults and, for an enrich_note write, folds the
metadata into the tool call's args. Single public `run`.
"""

from common import helper


def run(state: dict) -> dict:
    context = state.get("metadata_context") or {}
    metadata = helper.normalize(
        state.get("raw_metadata") or {}, state.get("metadata_text") or "",
        context.get("root_folders"), context.get("default_root"))
    trace = [*(state.get("metadata_trace") or []),
             {"kind": "node", "node": "classify_normalize", "status": "ok"}]
    update = {"metadata": metadata, "metadata_trace": trace}
    call = state.get("tool_call")

    if call and call.get("name") == "enrich_note":
        update["tool_call"] = {
            **call, "args": {**(call.get("args") or {}), **metadata},
        }

    return update
