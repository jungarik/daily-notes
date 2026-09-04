"""classify_propose node: the LLM proposes a note's metadata.

Reads the gathered context and asks the model for type/title/path/tags/priority
as strict JSON. Single public `run`.
"""

import json
import logging

import config
from agents.enrich.prompts import enrichment_prompt
from agents.runtime import model_gateway

logger = logging.getLogger(__name__)


def run(state: dict) -> dict:
    trace = [*(state.get("metadata_trace") or [])]

    if state.get("metadata_error"):
        return {"raw_metadata": {}, "metadata_trace": trace}

    context = state["metadata_context"]

    try:
        system = enrichment_prompt(
            context["known_paths"], context["known_tags"],
            context["related_notes"], context["root_folders"],
            context["default_root"], config.ENRICH_SIMILAR_MAX_DISTANCE)
        response = model_gateway.chat_completion(
            model=config.ENRICH_LLM_MODEL, temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": state["metadata_text"]}],
        )
        raw = json.loads(response.choices[0].message.content)
        trace.append({"kind": "node", "node": "classify_propose", "status": "ok"})

        return {"raw_metadata": raw, "metadata_trace": trace}
    except Exception as exc:
        logger.exception("Metadata proposal failed; using normalized fallback")
        trace.append({"kind": "node", "node": "classify_propose", "status": "error",
                      "error": type(exc).__name__})

        return {"raw_metadata": {}, "metadata_error": str(exc),
                "metadata_trace": trace}
