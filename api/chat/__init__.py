"""Chat section — the agentic chat tab (POST /api/chat, /api/chat/confirm).

endpoints.py → helper.py (resolves the caller's clock/locale) → the shared
`agents.conversation` controller. Settings are read via this section's own db.py.
The chat agent answers questions; when the user asks it to act, it hands the
write off to the enrich agent, which proposes the change for the user to confirm
(`/confirm`).
"""
