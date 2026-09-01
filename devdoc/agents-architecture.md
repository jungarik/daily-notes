# Agent architecture

The Web App Chat has two agents. Conversation owns interaction and all reads;
Enrich owns every write proposal and execution. Read tools and reminders are
capabilities of those agents, not separately registered workflows.

```text
agents/
├── contracts/                 shared typed handoff/result contracts
├── runtime/                   checkpoint and idempotent execution services
├── conversation/
│   ├── api.py                 public chat and read facade
│   ├── graph.py               stateful Chat workflow composition
│   ├── state.py
│   ├── routing.py
│   ├── prompts.py
│   ├── db.py                  thread projection persistence for the API
│   ├── nodes/                 model, read, dispatch, approval, final
│   └── tools/                 schemas, handlers, and tool-owned read queries
├── enrich/
│   ├── api.py                 public plan/execute facade
│   ├── graph.py               note-action, metadata, and reminder workflows
│   ├── state.py
│   ├── routing.py
│   ├── prompts.py
│   ├── domain.py              note creation/move/enrichment/reminders
│   ├── db.py                  all confirmed-write queries
│   ├── nodes/                 model, metadata, reminder, read, write, approval, final
│   └── tools/                 write schemas/handlers and internal context tools
└── bootstrap.py               registers only Enrich as Chat's specialist
```

Conversation executes its reads through tool handlers. Both `perform_action` and
`set_reminder` dispatch to Enrich; a typed mode tells Enrich whether to use its
general note planner or its reminder capability. Confirmation and idempotent
execution remain in the Conversation workflow. Telegram is unchanged.
