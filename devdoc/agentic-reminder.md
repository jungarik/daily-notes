# Reminder agent

Status: **implemented and wired only to Web App Chat.**

`agents/reminder/` is the single owner of reminder intent detection, natural-
language time resolution, planning, and creation for the Chat tab. It replaces
the former reminder responsibility in Enrich. Telegram deliberately keeps its
previous independent implementation.

## Public surfaces

- `plan_action(user_id, handoff, now, tz, locale)` resolves a typed chat request
  into `{name:"create_reminder", args:{text,remind_at}, summary}` without writing.
- `execute_action(...)` persists the backing note/chunks and reminder after Chat
  confirmation. It uses the already-resolved time rather than reinterpreting a
  relative expression during approval.

When the handoff resolves an existing note, the action contains its `note_id`
and execution attaches the reminder to that owner-scoped note instead of
creating a duplicate backing note. A reminder with no note reference keeps the
original create-note-and-reminder behavior.

## State, nodes, and edges

`ReminderState` holds the handoff, resolved reminder text, caller-local `now`,
`remind_at`, and `action`. `REMINDER_GRAPH` first resolves ordinal or pronoun
references against user-owned notes, then parses time. Resolved requests route
to `prepare_action -> END`; unresolved requests end with no action so Chat can
ask for a clearer date/time.

## Ownership and safety

- `domain.py` owns the multilingual hint gate, structured LLM parse, embedding
  for Chat-created reminder notes, and creation orchestration.
- `db.py` owns Chat reminder SQL. The backing note, chunks, and reminder are
  inserted in one transaction after confirmation.
- Chat owns confirmation and records `pending.agent="reminder"`.
- `api/telegram_bot` is not coupled to this agent and preserves its original
  parsing, immediate creation, and delivery lifecycle.

Config: `REMINDER_LLM_MODEL`, `REMINDER_FEW_COUNT`, and `REMINDER_LATER`.
