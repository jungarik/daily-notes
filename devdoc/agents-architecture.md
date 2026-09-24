# Agent architecture

Four peer agents and a loop. No agent knows another exists: the loop asks a
router who should run next, hands that agent a typed request, saves what comes
back, and repeats until someone needs the user or the reply has been written.
The full design — contracts, routing, the turn tree, idempotency — is
`devdoc/agent-loop.md`; this file is the map.

```text
agents/
├── contracts/                 every shape the farm exchanges, one per file:
│                               AgentSpec/Request/Result, UserContext, Ref,
│                               AGENT_KIND, HistoryEntry, Status, TurnOutcome,
│                               plus ToolResult and PlanRequest. Imports
│                               nothing — that is what keeps the graph acyclic
├── runtime/                   the machinery that runs a turn — none of it is
│   │                           any one agent's work
│   ├── loop.py              the turn loop
│   ├── registry.py            the roster; rejects duplicate names/entry tools
│   ├── state_store.py         the turn tree (agent_states)
│   ├── execution_ledger.py    at-most-once confirmed writes
│   └── checkpoint, model_gateway, execute_tool
├── router/                    who runs next — the farm's routing policy
│   ├── agent.py               a registered agent like any other; its SPEC
│   │                           runs case 3's model call and reports the
│   │                           choice as Ref(AGENT_KIND, name)
│   └── prompts.py
├── finder/                    reads and answers — the vault's reader
├── enricher/                  note writes: create, move, tag, link, classify
├── reminder/                  scheduling
│                               each: agent.py (start + resume), graph.py,
│                               state.py, prompts.py, nodes/ — SPEC is the
│                               only export
├── responder/                 the only agent that writes to the user
└── bootstrap.py               the one place an agent is named

tools/
├── finder/                    owner-scoped reads
├── enricher/                  note writes
├── reminder/                  the reminder write
└── responder/                 read_state — how the reply reads what the
                                turn's earlier hops produced
```

## How a turn runs

`api/chat_v2` calls `loop.start(message, context, references)`. Each hop:

1. **Route.** The responder is taken unconditionally when the turn is finishing;
   otherwise an entry tool resolves the agent for free; otherwise the router
   runs as a hop of its own and a model picks from the agents that have not yet
   run. It declines rather than guessing, and a decline falls through to the
   responder. A router hop is saved and lands in the history like any other, but
   does not spend the hop budget — routing is free.
2. **Run.** The agent gets an `AgentRequest` and returns an `AgentResult` —
   `done`, `needs_input` (it wants the user to confirm a write), or `failed`.
3. **Record.** One row in `agent_states`, and one entry in the turn history.
   One agent, one entry: a resumed hop replaces its own `needs_input`.

The loop ends when an agent produced a reply, or asked for the user, or the hop
budget ran out. `AGENT_MAX_HOPS` counts the reply.

## The rules that keep it extendable

- **An agent names no peer.** It reports what it did as typed `Ref`s; routing is
  the loop's. `tests/test_agent_structure.py` enforces this by import scan,
  and the same file checks that `contracts/` imports nothing — the two scans
  together are what keep the dependency graph acyclic.
- **The history is derived, never written.** The loop builds each entry from a
  result, so an agent cannot describe itself favourably.
- **Only the responder speaks.** Work agents put their output in
  `AgentResult.state`; the responder reads it through `read_state` — the one
  tool in `tools/responder/`, and the only caller of it — and phrases the
  reply. That is why voice and localisation exist in one place.
- **Writes happen at most once.** A confirmed action is keyed by its own
  fingerprint, not by the hop, so a retried confirm replays the stored outcome.
- **Routing and the loop are separate packages.** `router/` decides who runs;
  `runtime/loop.py` runs them. They meet only in `bootstrap.py`, which registers
  the router in the roster the loop is handed — so a new routing rule never
  touches the loop, and neither imports the other (enforced in
  `tests/test_agent_structure.py`). The loop reaches the router by the name the
  registry knows it by; `AGENT_KIND`, the one `Ref.kind` the loop reads, is a
  contract for exactly that reason.
- **Extend by data.** A new agent is a spec plus a registry line in
  `bootstrap.py`; a new tool is a file in `tools/<agent>/`. Neither touches the
  loop.

Telegram is unchanged: `api/telegram_bot` keeps its own one-shot enrichment and
reminder handling and does not use the farm.
