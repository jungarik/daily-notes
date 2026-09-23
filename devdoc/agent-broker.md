# Agent broker

**Status:** Phases 1–2 built (`agents/broker/`, `agents/reminder/agent.py`,
migration 0022). Nothing calls the broker yet — chat still runs on the handoff
path, which this supersedes at Phase 5.

## Goal

A farm of peer agents. The broker is the only thing that routes: it picks the
next agent, hands it a message, saves what it produced, and repeats until the
responder writes the user's reply. Agents never name each other. Adding one is a
spec entry plus its own folder.

```
                 ┌─────────────────────────────┐
  POST /api/chat │           broker            │
       ───────▶  │  route → run → save → route │
                 └─────────────────────────────┘
                    │        │        │       │
            conversation  enrich  reminder  responder
             (answers)   (writes) (schedules) (replies)
```

## The two contracts

Every agent implements these and nothing else:

```python
@dataclass(frozen=True)
class AgentSpec:
    name: str
    description: str          # what the router reads when it has to choose
    entry_tools: tuple[str]   # tool names that route here without a router call
    may_read: tuple[str]      # whose states this agent may fetch ("*" for all)
    start: Callable           # (AgentRequest) -> AgentResult
    resume: Callable | None   # (token, decision, context) -> AgentResult
```

`resume` takes a fresh `context` because a confirmation arrives in a later
request: the clock has moved on since the ask, and the agent must resolve against
now rather than against then.

```python
@dataclass(frozen=True)
class AgentResult:
    status: Literal["done", "needs_input", "failed"]
    state: dict               # everything the run produced (below)
    produced: list[Ref]       # typed refs to what it made — the history source
    ask: dict | None          # needs_input: what the user must confirm/choose
    token: str | None         # needs_input: opaque, agent-owned
    error: str | None         # failed
```

An agent that never pauses simply never returns `needs_input`. A LangGraph agent
puts its `thread_id` in `token`; a plain-Python agent puts whatever it likes.
The broker and the endpoint never look inside it.

## The request

One hop. Same envelope shape as the stashed messaging work, which is what makes
a turn reconstructable as a tree:

```python
class UserContext(TypedDict, total=False):
    user_id: int              # the turn's owner, written down exactly once
    now: str                  # ISO string, not a datetime — the envelope is JSON
    tz: str | None
    locale: str

@dataclass(frozen=True)
class AgentRequest:
    request_id: str
    correlation_id: str       # the turn
    causation_id: str | None  # the state that produced this hop
    agent: str                # who it is addressed to
    message: str              # what the user asked
    context: UserContext      # this request's owner and clock
    references: dict          # material the caller had already resolved
    history: tuple[HistoryEntry]  # what already ran this turn — see below
    hops_left: int
```

Three things this shape is deliberate about:

- **The owner lives in `context` and nowhere else.** `broker.start` does not take
  a `user_id` beside it. Two copies of the same fact drift, and the failure mode
  is ugly: the store writes a row for one user while an agent writes a note for
  another.
- **`context` is typed but open** (`total=False`). A `TypedDict` is checked where
  a type checker runs and is still a plain dict at runtime, so it serialises and
  an agent can read a key the contract has not heard of. A closed dataclass would
  mean editing a shared contract to add a per-agent field — that would limit the
  farm, which is the thing this design exists to avoid. `user_id` is therefore
  enforced at runtime rather than by the type: the broker subscripts it, so a
  context without one raises instead of writing a row for nobody
  (`test_a_context_without_an_owner_fails_loudly`).
- **`references` is separate from `context`.** The clock belongs to every turn;
  note ids and citations belong to the agent that was handed them. Keeping them
  apart stops the shared type growing a field per agent. An agent that wants more
  than it was given calls `read_state`.

`history` is a compact per-agent view, not the states themselves. An agent that
needs more calls its `read_state` tool (below).

### The history has no prose

A history entry is closed — there is no free-text field, so there is nothing that
can be written vaguely:

```python
@dataclass(frozen=True)
class Ref:
    kind: str                 # "note", "reminder", "link" — opaque to the broker
    id: str

@dataclass(frozen=True)
class HistoryEntry:
    agent: str
    status: Literal["done", "needs_input", "failed"]
    produced: list[Ref]
    error: str | None
    state_id: str            # the handle `read_state` takes
```

It carries no `state` of its own — the full working state stays in
`agent_states`, reachable only through `read_state`. `state_id` is what makes
that reachable: without it an agent would be told a hop happened and have no way
to ask what it did.

Rules that keep it reliable:

- **The broker writes it, never the agent.** The entry is derived from the
  `AgentResult` the broker already holds. An agent cannot describe itself well or
  badly, because it does not describe itself at all.
- **`kind` is opaque.** The broker checks that it is a non-empty string with an
  id beside it and never looks at the value. Agents coin their own kinds; there
  is no shared vocabulary module, consistent with the project having no shared
  domain layer.
- **A malformed result fails the hop.** If `produced` does not validate, the
  broker writes a `failed` state and routes to the responder — the same path as
  any other agent failure. It is not silently replaced with an empty entry,
  because a history that lies is worse than a turn that stops.
- **An *empty* `produced` is valid.** An agent that searched and found nothing
  genuinely produced nothing, and the broker cannot tell that apart from an agent
  that forgot to report. So the guard is a per-agent test — "enrich, given this
  input, reports the note it wrote" — not a broker rule.
- **One agent, one entry.** A `needs_input` entry is *replaced* by the outcome
  when the agent resumes. `agent_states` keeps both rows — that is the audit
  record — but the history shows the outcome, so the router's "do not re-route to
  an agent that already ran" rule needs no special case for paused agents.

The case-3 router therefore sees the roster, the user's original message, and
this list. The message carries the intent; the history says only what is already
done. The broker does **not** expand ids into titles — that would cost a read per
hop to improve a prompt that is already sufficient.

The responder is unaffected by any of this: it has `may_read=["*"]` and reads
whole states, so removing prose from the history costs the user-facing reply
nothing.

## State, and the turn tree

Every agent run writes one row. The full working state is saved — instructions,
messages, tool calls, trace — so a turn can be replayed.

```sql
CREATE TABLE agent_states (                      -- migration 0022
    state_id       uuid PRIMARY KEY,
    correlation_id uuid NOT NULL,                -- the turn
    causation_id   uuid,                         -- the state that caused this
    user_id        bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent          text NOT NULL,
    status         text NOT NULL,                -- done|needs_input|failed
    state          jsonb NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON agent_states (correlation_id);
```

No retention job yet — we keep everything and revisit when the table bites.
**Note this holds user note text**, so it inherits the same handling rules as
`notes` (per-user, deleted with the user via the cascade).

### Reading another agent's state

Not a broker API that agents import — a **tool**, scoped by the registry:

```python
AGENTS = {
    "responder": AgentSpec(..., entry_tools=[],                  may_read=["*"]),
    "reminder":  AgentSpec(..., entry_tools=["set_reminder"],    may_read=["conversation"]),
    "enrich":    AgentSpec(..., entry_tools=["perform_action"],  may_read=[]),
}
```

The broker gives each agent a `read_state(state_id)` tool restricted to
`may_read`, the same shape as `CONTEXT_TOOLS` restricts `execute_allowed_tool`
today. An agent asking for a state it may not read gets an error, not the row.

## Routing

The broker owns routing, but **it does not spend a model call on a decision that
has already been made.** Three cases, in order:

1. **The responder hop is unconditional.** It always runs last, so there is
   nothing to decide. No router call, by construction.
2. **A tool name resolves it.** When the previous model call already chose —
   `set_reminder`, `perform_action` — the tool name *is* the route. The broker
   looks it up in `entry_tools` across the registry. No router call. This is the
   common path and covers every single-agent turn.
3. **Otherwise, ask.** When an agent finishes and more than one agent could
   plausibly follow, the broker makes one model call: the roster (`name` +
   `description`) plus the history of the turn so far — so it will not re-route to
   an agent that already ran — returning the next agent's name.

So a typical turn spends **zero** router calls and a genuinely multi-agent turn
spends one. `entry_tools` lives on the spec, meaning the agent declares what
routes to it and the broker owns the lookup — this is `MODE_AGENTS` inverted, not
`MODE_AGENTS` restored. No agent imports another, and adding an agent is still
one registry entry.

A tool name claimed by two specs is a startup error, not a runtime tie-break.

Bound: `AGENT_MAX_HOPS`. Exhausting it is a failure, not a silent stop.

**Keeping case 3 honest.** It is the rare path, so it is the one that rots.
`AGENT_ROUTER_ALWAYS=1` skips cases 1–2 and forces every hop through the model
router; it is on in dev and in the eval harness. The path that production almost
never takes is the path every local turn takes, which is the cheapest place to
find out it broke.

**Where it lives.** `agents/broker/router.py` holds `Router.select_agent` and
nothing else; the broker owns the loop and is handed a router. A new routing rule
changes one file, and a change to how a hop is saved or suspended never touches
routing. `Router(registry, select_model=None, always_ask_model=False)` —
`select_model` is the case-3 seam and is still empty, so today a turn routes by
entry tool or ends.

The router is also the farm's only holder of the registry: `Broker` takes
`(store, ledger, router)` and looks nothing up itself, resolving a suspended
turn's agent through `router.get_agent(name)`, which raises on an unknown name.
The composition root keeps its own reference for things that are not routing —
the Phase 3 `read_state` tool and its `may_read` allowlist come from there, not
through the router.

## The responder

A peer agent whose job is the user-facing reply, and the **last hop of every
turn** — including failed ones, so the user gets a sensible message rather than a
raw error. It may call read tools of its own to phrase the answer well, and may
read any state (`may_read=["*"]`).

Work agents therefore never write user-facing prose. That is the one rule that
keeps voice and localisation in a single place.

**It runs on a suspend too.** A `needs_input` turn does not end, but it does
return to the user, so the responder runs before the broker hands back — turning
the agent's raw `ask` into the confirmation text. Otherwise "all prose in one
place" would be false for exactly the screen where wording matters most.

**Prose is the only thing it owns.** Citations and the confirm `action` payload
are passed through by the broker from `produced`, not assembled by the responder.
So a responder failure costs wording and nothing else — the note is still cited,
the action is still confirmable.

**It has a fallback that cannot fail.** When the responder's model call errors,
the broker templates the history instead: *"Saved 1 note, set 1 reminder."* Terse,
never wrong, and `produced` is already the right shape to render. The reply
degrades in quality, never in truth — the user is never left unsure whether their
note was saved.

## Suspend and resume

Synchronous: `POST /api/chat` blocks while the broker drives hops. When an agent
returns `needs_input`, the broker stops and returns it; the endpoint stores the
turn id in the column it already owns:

```python
pending = {
    "correlation_id": "...",
    "agent": "reminder",
    "token": "<opaque, agent-owned>",
    "ask": {"kind": "confirm", "action": {...}},
}
```

`POST /api/chat/confirm` calls `broker.resume(correlation_id, decision)`, which
reloads the tree from `agent_states`, calls that agent's `resume(token, ...)`,
and carries on to the responder.

**The checkpointer is not involved in the tree.** It keeps doing exactly one
job: pausing and resuming a single agent's own graph. Two mechanisms, two
purposes.

## Idempotency

The broker owns at-most-once execution of confirmed writes, absorbing
`execution_ledger`.

**Constraint that must hold:** the key stays derived from the *action*, not from
the hop. A `message_id` changes when a hop is re-driven (a retried confirm, a
recovered turn), so keying on it would let the same write run twice. Keep
`action_id`'s uuid5-over-the-action-fingerprint derivation exactly as it is —
only the caller moves.

## Failure

An agent failure is a `failed` state in the tree. The broker does not retry; it
routes to the responder, which explains. The turn's HTTP response is still 200
with a reply — an error is a thing the user is told, not a stack trace.

## Phases

| | | reversible? |
|---|---|---|
| **1** ✅ | `AgentSpec`, `AgentResult`, `AgentMessage`, broker skeleton, `agent_states` + migration 0022. Nothing wired. | yes |
| **2** ✅ | Port `reminder` (smallest). Old handoff path still serves chat. | yes |
| **3** | Port `enrich`. | yes |
| **4** | Add `responder`. Broker drives reminder + enrich end to end behind a flag. | yes |
| **5** | `conversation` becomes a peer; endpoint calls the broker; delete `handoff_dispatch`, `HANDOFF_SPECIALISTS`, `MODE_AGENTS`. | no |

Phase 4 is the checkpoint: if the broker cannot drive a two-hop turn (enrich
writes a note, reminder schedules it, responder explains both) without an agent
knowing about another, stop before Phase 5.

## Open risks

- **The responder adds a hop to every turn, including trivial ones.** A plain
  question now costs conversation + responder where it used to cost one agent.
  The fallback template makes it safe, not fast. Measure at Phase 4; if it hurts,
  the answer is probably letting `conversation` mark its own output as
  final-quality prose, which weakens the one-place rule.
- **`AGENT_ROUTER_ALWAYS` makes dev behave unlike production** by construction.
  That is the point, but it means a routing bug that only appears in the
  `entry_tools` fast path will not show up locally. Case 1–2 need their own
  (cheap, model-free) assertions.
- **Two idempotency scopes now coexist**: the broker's `action_id` ledger for
  confirmed writes, and the checkpointer for graph resume. A turn that fails
  between them — write committed, checkpoint not advanced — is the case worth
  testing hardest before Phase 5.
