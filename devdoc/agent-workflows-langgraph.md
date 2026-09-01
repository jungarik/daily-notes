# Agent workflows on LangGraph

Status: **implemented.** Conversation and Enrich use compiled LangGraph
`StateGraph` workflows. Knowledge is a Conversation capability and Reminder is
an Enrich capability; neither is a separately registered agent.
Existing API response shapes remain unchanged.

## Persistence boundary

`PostgresSaver` is the execution-state source of truth. Each graph uses a scoped
thread id (`chat:<id>` or `enrich:<id>`), checkpoints every node boundary, and
resumes failures from the last successful node. The saver schema is installed
by API startup.

`chat_threads.messages` and `chat_threads.pending` remain an application
projection for ownership checks, API/UI reads, and evaluation. They no longer
decide which workflow node resumes. State contains only serializable data;
runtime tool contexts are reconstructed inside nodes with strict checkpoint
deserialization enabled.

## Chat graph

`ChatState` carries provider messages, per-turn context, step count, current tool
call, terminal response, pending action, specialist identity, and an ordered
cross-turn `reference_notes` list. Response citations remain turn-local.
Before the model node, `pre_route` deterministically detects obvious reminder
requests and sends them to Enrich as `set_reminder`, avoiding one LLM routing
call.

```mermaid
flowchart TD
    S((START)) -->|turn| PR[pre_route]
    S -->|legacy pending| H[approval / interrupt]
    PR -->|obvious reminder| RM[reminder_agent]
    PR -->|otherwise| M
    M -->|no tool| E((END))
    M -->|read| T[read_tool]
    M -->|perform_action| A[enrich_agent]
    M -->|set_reminder| RM[reminder_agent]
    T -->|budget remains| M
    T -->|budget used| F[final]
    A --> H
    A -->|unresolved| M
    RM --> H
    RM -->|unresolved| M
    H -->|Command resume| M
    F --> E
```

Both handoff branches plan through Enrich; `reminder_agent` names the reminder
mode, not a separately registered agent. `approval` interrupts with the stable action id and proposal. The confirm API
uses `Command(resume=approve)`, so planning nodes are not rerun. After approval,
the node executes through Enrich. Old projections also default to Enrich.

## Enrich graphs

`EnrichState` carries messages, context, step count, tool call, terminal state,
pending write, and confirmation flags.

```mermaid
flowchart TD
    S((START)) -->|turn| M[model]
    S -->|legacy pending| H[approval / interrupt]
    M -->|no tool| E((END))
    M -->|read| T[read_tool]
    M -->|metadata write| MC[metadata_context]
    M -->|reminder write| RM[reminder_model]
    M -->|simple write| P[pending_write]
    T -->|budget remains| M
    T -->|budget used| F[final]
    MC --> MM[metadata_model]
    MM --> MV[metadata_validation]
    MV --> P
    RM --> RV[reminder_validation]
    RV -->|resolved| P
    RV -->|unresolved| F
    P --> H
    H -->|Command resume| M
    F --> E
```

The stateless Chat handoff uses `ACTION_PLAN_GRAPH`:
`START -> plan_model -> plan_read -> plan_model ... -> validate_write -> END`.
It can read note context, paths, and tags, but only returns a validated write
proposal. The handoff itself is typed and includes conversation and entities.

## Reminder capability

The main Enrich graph and `REMINDER_PLAN_GRAPH` both use
`reminder_model -> reminder_validation`. The model node resolves
natural-language time; validation uses deterministic domain logic to resolve
referenced notes and return a frozen `create_reminder` proposal. The standalone
plan graph is used for Chat handoff evaluation and has no loop, checkpoint, or
independent approval boundary.
Telegram keeps its previous local
reminder detection, creation, delivery, claiming, list, cancel, and snooze logic.

## Invariants

- Chat has no direct write handler.
- Every Chat write requires explicit confirmation.
- Enrich owns all confirmed writes, including reminders.
- Agent chat-completion calls go through `agents/runtime/model_gateway.py`.
- Tool selection is single-call and loops are bounded.
- Reminder attachment is scoped by both note id and user id.
- Existing `/api/chat` and `/api/chat/confirm` contracts are unchanged.
