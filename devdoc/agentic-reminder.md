# Reminder capability

Reminder handling for Web App Chat is a capability of the Enrich agent, not a
separate agent. `REMINDER_PLAN_GRAPH` runs an explicit reminder model node to
resolve natural-language time, then a validation node uses deterministic domain
logic to resolve conversational note references and return a `create_reminder`
proposal. Conversation provides the confirmation boundary, and Enrich executes
the approved action through the shared idempotency ledger.

Reminder SQL lives in `agents/enrich/db.py`. Telegram retains its independent
reminder parsing, creation, and delivery implementation.
