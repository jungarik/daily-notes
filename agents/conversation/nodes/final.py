"""Tool-free fallback node for the conversation graph."""

from agents.conversation.nodes import model
from agents.conversation.state import ChatState


def run(state: ChatState) -> dict:
    try:
        msg = model.complete(state["messages"], use_tools=False).choices[0].message
        reply = msg.content or "I couldn't finish that in time."
    except Exception:
        reply = model.MODEL_UNAVAILABLE_REPLY
    return {"messages": [*state["messages"], {"role": "assistant", "content": reply}],
            "status": "answer", "reply": reply, "pending": None}
