"""propose node: the model proposes a note's metadata.

Reads the gathered context and asks for type/title/path/tags/priority as strict
JSON. A failure here is not fatal: `normalize` fills canonical defaults from the
note's own text, so the turn still produces a filing rather than nothing.
Single public `run`.
"""

import json
import logging

import config
from agents.classifier.prompts import classification_prompt
from agents.classifier.state import ClassifyState
from agents.runtime import model_gateway

logger = logging.getLogger(__name__)


def _build_request(context: dict, text: str) -> dict:
    return {
        "model": config.ENRICH_LLM_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{
            "role": "system",
            "content": classification_prompt(
                context["known_paths"],
                context["known_tags"],
                context["related_notes"],
                context["root_folders"],
                context["default_root"],
                config.ENRICH_SIMILAR_MAX_DISTANCE),
        }, {
            "role": "user",
            "content": text,
        }],
    }


def run(state: ClassifyState) -> dict:
    trace = [*(state.get("trace") or [])]

    if state.get("error"):
        return {"raw_metadata": {}, "trace": trace}

    try:
        model_response = model_gateway.chat_completion(
            **_build_request(state["context"], state["text"]))
        raw_metadata = json.loads(model_response.choices[0].message.content)
        trace.append({"kind": "node", "node": "propose", "status": "ok"})

        return {"raw_metadata": raw_metadata, "trace": trace}
    except Exception as exc:
        logger.exception("Metadata proposal failed; using normalized fallback")
        trace.append({"kind": "node", "node": "propose", "status": "error",
                      "error": type(exc).__name__})

        return {"raw_metadata": {}, "error": str(exc), "trace": trace}
