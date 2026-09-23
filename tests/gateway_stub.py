"""One model-gateway stand-in, shared by every test file that needs it.

`agents/runtime/model_gateway.py` reaches the OpenAI client, so tests replace it
in `sys.modules` before importing anything that binds it. Four files need that,
and the installer has to satisfy two rules at once:

  - **idempotent** — the second caller reuses the first one's recorder, so every
    module that already bound the stub keeps pointing at the dict the tests read;
  - **first, before any real import** — a module that has already bound the real
    gateway will keep it, whatever lands in `sys.modules` afterwards.

The second rule is why this is a module rather than a copy per file. Importing
`agents.router` now reaches the gateway (case 3 lives in `router/agent.py`), so
`tests/test_loop.py` pulls it in early just by importing `Router` — and it is
alphabetically third. Every file that touches a model calls `install()` at the
top, before its own imports, so whichever runs first wins with the stub.
"""

import sys
import types


def install() -> dict:
    """The shared recorder: `{"response", "error", "requests"}`.

    Set `response` to what the model should return, or `error` to an exception
    it should raise. `requests` collects every call's kwargs.
    """
    existing = sys.modules.get("agents.runtime.model_gateway")

    if existing is not None and hasattr(existing, "GATEWAY"):
        return existing.GATEWAY

    gateway = {"response": None, "error": None, "requests": []}

    module = types.ModuleType("agents.runtime.model_gateway")

    def chat_completion(**model_request):
        gateway["requests"].append(model_request)

        if gateway["error"] is not None:
            raise gateway["error"]

        return gateway["response"]

    module.chat_completion = chat_completion
    module.ModelGatewayError = RuntimeError
    module.GATEWAY = gateway
    sys.modules["agents.runtime.model_gateway"] = module

    return gateway
