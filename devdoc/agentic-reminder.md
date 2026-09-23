# Agentic reminders

Status: **implemented as its own agent.** `agents/reminder/` is a full
vertical: `agent.py` (the whole agent — planning and the confirmed write), a
two-node planning graph (`resolve` -> `build`), its own state, prompt, and
`tools/reminder/` (`create_reminder`, `get_note_context`, and their SQL).
It imports nothing from another agent, and `SPEC` is its only export.

The loop routes a scheduling turn here — either because the turn arrived with
the `set_reminder` entry tool, or because the model router picked it from the
roster by description. Enrich does not carry `create_reminder` in its tool
registry, so only this agent can schedule.

`start` hydrates the notes an instruction references through its own
`get_note_context` tool, runs `PLAN_GRAPH`, and gets back the `create_reminder`
write — or None when no time could be resolved, which is an ordinary outcome
("remind me about this sometime"), not a failure. `resolve` gates on a cheap
regex before spending an LLM call; `build` turns a resolved datetime into the
proposal, attaching the referenced note when the instruction points at one.

`start` then pauses the turn (`needs_input` plus an `ask`), and `resume`
performs the write on approval through `tools/reminder/` — at most once, via
the execution ledger. A decline runs nothing, so there is no decline branch
here.

Telegram retains its own independent reminder parsing, creation and delivery in
`api/telegram_bot` and does not use this agent.
