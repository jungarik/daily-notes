"""Chat section — the agentic chat tab (POST /api/chat, /api/chat/confirm).

endpoints.py → helper.py (turn orchestration) → the shared `agents.chat`
reasoning engine + `common` (user settings, thread persistence). The agent loop
is deliberately shared infra, so this section reuses it rather than duplicating a
tool-calling loop.
"""
