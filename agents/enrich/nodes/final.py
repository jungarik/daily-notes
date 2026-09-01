"""Tool-free fallback node for the Enrich graph."""

from agents.enrich.nodes import model
from agents.enrich.state import EnrichState


def run(state: EnrichState) -> dict:
    msg = model.complete(state["messages"], use_tools=False).choices[0].message
    reply = msg.content or "I couldn't finish that in time."
    return {"messages": [*state["messages"],
                         {"role": "assistant", "content": reply}],
            "status": "answer", "reply": reply, "pending": None}
