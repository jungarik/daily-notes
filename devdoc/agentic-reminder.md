# Agentic reminders

Status: **implemented as its own specialist.** `agents/reminder/` is a full
vertical: `handoff_api.py` (`plan_action` / `execute_action`), a two-node
planning graph (`resolve` -> `build`), its own state, prompt, and
`tools/reminder/` (`create_reminder`, `get_note_context`, and their SQL).
It imports nothing from the enrich agent.

Chat's `set_reminder` handoff maps to it in the composition root:
`MODE_AGENTS["reminder"] = "reminder"`, `registry.register("reminder", ...)`.
Enrich no longer carries `create_reminder` in its tool registry, so only this
agent can schedule.

`plan_action` hydrates the notes an instruction references through its own
`get_note_context` tool, runs `PLAN_GRAPH`, and returns the `create_reminder`
write or None when no time could be resolved. `resolve` gates on a cheap
regex before spending an LLM call; `build` turns a resolved datetime into the
proposal, attaching the referenced note when the instruction points at one.

---

# Reminder capability

Reminder handling for Web App Chat is a capability of the Enrich agent, not a
separate agent. `REMINDER_PLAN_GRAPH` runs an explicit reminder model node to
resolve natural-language time, then a validation node uses deterministic domain
logic to resolve conversational note references and return a `create_reminder`
proposal. Conversation provides the confirmation boundary, and Enrich executes
the approved action through the shared idempotency ledger.

Reminder SQL lives in `agents/enrich/db.py`. Telegram retains its independent
reminder parsing, creation, and delivery implementation.
