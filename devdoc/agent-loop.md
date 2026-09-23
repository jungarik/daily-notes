# The agent loop

**Status:** built and live. The chat tab runs on the farm
(`api/chat_v2` → `agents/bootstrap.loop`), with `finder`, `enrich`, `reminder`
and `responder` registered. The handoff path this replaced — `conversation`,
`handoff_dispatch`, `specialist_registry`, `api/chat` — has been deleted.

## Goal

A farm of peer agents. The turn loop is the only thing that routes: it picks the
next agent, hands it a message, saves what it produced, and repeats until the
responder writes the user's reply. Agents never name each other. Adding one is a
spec entry plus its own folder.

```
                 ┌─────────────────────────────┐
POST /api/chat/v2│          turn loop          │
       ───────▶  │  route → run → save → route │
                 └─────────────────────────────┘
                    │        │        │       │
               finder     enrich  reminder  responder
             (answers)   (writes) (schedules) (replies)
```

## The two contracts

Every agent implements these and nothing else. They live in
`agents/contracts/`, one type per module, importing nothing — which is what
lets the loop, the router, the store and four agents agree on shapes without
importing each other:

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
    reply: str | None         # in practice only the responder sets it
```

`reply` is a declared field rather than a `state` key so the loop can carry it
out to `TurnOutcome.reply` without looking inside an agent's state or knowing
which agent the responder is. A hop that sets it ends the turn.

An agent that never pauses simply never returns `needs_input`. A LangGraph agent
puts its `thread_id` in `token`; a plain-Python agent puts whatever it likes.
The loop and the endpoint never look inside it.

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

- **The owner lives in `context` and nowhere else.** `loop.start` does not take
  a `user_id` beside it. Two copies of the same fact drift, and the failure mode
  is ugly: the store writes a row for one user while an agent writes a note for
  another.
- **`context` is typed but open** (`total=False`). A `TypedDict` is checked where
  a type checker runs and is still a plain dict at runtime, so it serialises and
  an agent can read a key the contract has not heard of. A closed dataclass would
  mean editing a shared contract to add a per-agent field — that would limit the
  farm, which is the thing this design exists to avoid. `user_id` is therefore
  enforced at runtime rather than by the type: the loop subscripts it, so a
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
    kind: str                 # "note", "reminder", "link" — opaque to the loop
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

- **The loop writes it, never the agent.** The entry is derived from the
  `AgentResult` the loop already holds. An agent cannot describe itself well or
  badly, because it does not describe itself at all.
- **`kind` is opaque.** The loop checks that it is a non-empty string with an
  id beside it and never looks at the value. Agents coin their own kinds; there
  is no shared vocabulary module, consistent with the project having no shared
  domain layer.
- **A malformed result fails the hop.** If `produced` does not validate, the
  loop writes a `failed` state and routes to the responder — the same path as
  any other agent failure. It is not silently replaced with an empty entry,
  because a history that lies is worse than a turn that stops.
- **An *empty* `produced` is valid.** An agent that searched and found nothing
  genuinely produced nothing, and the loop cannot tell that apart from an agent
  that forgot to report. So the guard is a per-agent test — "enrich, given this
  input, reports the note it wrote" — not a loop rule.
- **One agent, one entry.** A `needs_input` entry is *replaced* by the outcome
  when the agent resumes. `agent_states` keeps both rows — that is the audit
  record — but the history shows the outcome, so the router's "do not re-route to
  an agent that already ran" rule needs no special case for paused agents.

The case-3 router therefore sees the roster, the user's original message, and
this list. The message carries the intent; the history says only what is already
done. The loop does **not** expand ids into titles — that would cost a read per
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

Not a loop API that agents import — a **tool**, scoped by the registry:

```python
AGENTS = {
    "responder": AgentSpec(..., entry_tools=[],                  may_read=["*"]),
    "finder":    AgentSpec(..., entry_tools=[],                  may_read=[]),
    "reminder":  AgentSpec(..., entry_tools=["set_reminder"],    may_read=[]),
    "enrich":    AgentSpec(..., entry_tools=["perform_action"],  may_read=[]),
}
```

`read_state(state_id)` lives in `tools/responder/` — `TOOLS`, `CONTEXT_TOOLS`, `db`,
the same shape as every other tool namespace — and an agent runs it through
`execute_allowed_tool` with its own `may_read` in the context. It is a
**context** tool, never advertised in `TOOL_SPECS`: a node calls it
deterministically, the model never asks for it.

**Only the responder reads today**, which is why the namespace is named for
it and why every other `may_read` is empty. An allowlist for a tool an agent
never calls is config nothing exercises — it goes stale silently, as those
three did while still naming the deleted `conversation` agent. A second
reader grants itself a scope at the same time it starts reading.

Two independent checks, and only one of them is a security boundary.
`tools/responder/db.get_state` scopes the row to the caller's `user_id` **in SQL**,
so no allowlist can cross an owner. `may_read` is the softer one: every agent is
our own code, so it catches a wiring mistake rather than a lying caller. An agent
asking for a state it may not read gets an error, not the row — and the error
names the agent that was refused, never what its state held.

The responder reads deterministically, before its single model call, rather than
offering `read_state` as something the model may request: the reply path runs on
every turn and does not need a round-trip to decide it wants the record it is
about to report on. A state it cannot read costs detail, never the reply — the
hop is skipped with a warning.

## Routing

The loop owns routing, but **it does not spend a model call on a decision that
has already been made.** Three cases, in order:

1. **The responder hop is unconditional.** It always runs last, so there is
   nothing to decide. No router call, by construction.
2. **A tool name resolves it.** When the previous model call already chose —
   `set_reminder`, `perform_action` — the tool name *is* the route. The loop
   looks it up in `entry_tools` across the registry. No router call. This is the
   common path and covers every single-agent turn.
3. **Otherwise, ask.** When an agent finishes and more than one agent could
   plausibly follow, the loop runs the router as a hop: it gets the candidates
   (`name` + `description`) in `references` plus the history of the turn so far
   — so it will not re-route to an agent that already ran — and makes one model
   call returning the next agent's name. The candidate list is the loop's, built
   from the agents that have not yet run; an empty list short-circuits, so a
   turn with nothing left to do never spends a call finding that out.

So a typical turn spends **zero** router calls and a genuinely multi-agent turn
spends one. `entry_tools` lives on the spec, meaning the agent declares what
routes to it and the loop owns the lookup — this is `MODE_AGENTS` inverted, not
`MODE_AGENTS` restored. No agent imports another, and adding an agent is still
one registry entry.

A tool name claimed by two specs is a startup error, not a runtime tie-break.

Bound: `AGENT_MAX_HOPS`. Exhausting it is a failure, not a silent stop.

**Keeping case 3 honest.** It is the rare path, so it is the one that rots.
`AGENT_ROUTER_ALWAYS=1` skips cases 1–2 and forces every hop through the model
router; it is on in dev and in the eval harness. The path that production almost
never takes is the path every local turn takes, which is the cheapest place to
find out it broke.

**Where it lives.** `agents/router/agent.py` is **an agent**, not a service the
loop calls. It has a `SPEC` like every peer, `SPEC` is the whole surface of
`agents/router/`, and `bootstrap.py` registers it alongside the other four. Its
`start` reads `references["candidates"]`, calls `select_agent_name` (one JSON
call naming an agent from that list, or `null`), and reports the choice the way
every agent reports its work — `produced=(Ref(AGENT_KIND, name),)`. So a routing
decision is an ordinary row in `agent_states` and an ordinary `HistoryEntry`:
the turn tree records *why* the next agent ran, not just that it did.

Two things follow from that, and both are deliberate:

- **Router hops are free.** The loop counts only entries whose agent is not the
  router against `AGENT_MAX_HOPS`, so making routing visible did not halve the
  work a turn can do.
- **The router is never a candidate.** `registry.list_agents()` leaves out both
  singletons — the responder, which takes the last hop by construction, and the
  router, because offering it would let a decision pick itself.

It is conservative by construction: an unparseable answer, a missing key, or a
name that was not offered all collapse to `None`, which means an empty
`produced`, which the loop reads as "the responder takes the hop". Routing badly
is worse than routing nowhere, and the user gets a reply either way. Importing
the router reaches the OpenAI client, which is why `tests/test_loop.py` installs
the shared gateway stub first (`tests/gateway_stub.py`).

`Loop` takes `(store, ledger, registry)` and does its own lookups:
`find_responder()` for case 1, `find_by_entry_tool()` for case 2,
`find_router()` and `list_agents()` for case 3, and `get(name)` to resolve a
suspended turn's agent (it raises on an unknown name). The one value that
crosses from routing to the loop is `AGENT_KIND` — the single reserved
`Ref.kind`, and a contract rather than a literal in two files precisely because
the loop and the router may not import each other. `read_state` needs none of
this: an agent passes its own `may_read` in the tool context, so nothing has to
look a spec up to make the check.

## The responder

A peer agent whose job is the user-facing reply, and the **last hop of every
turn** — including failed ones, so the user gets a sensible message rather than a
raw error. It may read any state (`may_read=["*"]`).

**It is an ordinary hop, not a step outside the loop.** The loop takes it
directly when the turn is finishing — one flag, set when the budget's last slot
is reached or a hop returned `needs_input` or `failed` — and never asks the
router, because there is nothing to decide. The router never inspects a status
itself. A hop that returns a `reply` ends the loop — which is also why a confirm gets a second reply even though the
turn's history already holds the first.

`AGENT_MAX_HOPS` therefore counts the reply: the default of 5 is four work hops
plus one. A farm with no responder registered simply ends one hop early with no
reply.

Work agents therefore never write user-facing prose. That is the one rule that
keeps voice and localisation in a single place.

**It runs on a suspend too.** A `needs_input` turn does not end, but it does
return to the user, so the responder runs before the loop hands back — turning
the agent's raw `ask` into the confirmation text. Otherwise "all prose in one
place" would be false for exactly the screen where wording matters most.

**Prose is the only thing it owns.** Citations and the confirm `action` payload
are passed through by the loop from `produced`, not assembled by the responder.
So a responder failure costs wording and nothing else — the note is still cited,
the action is still confirmable.

**It has a fallback that cannot fail.** When the responder's model call errors,
the loop templates the history instead: *"Saved 1 note, set 1 reminder."* Terse,
never wrong, and `produced` is already the right shape to render. The reply
degrades in quality, never in truth — the user is never left unsure whether their
note was saved.

## Suspend and resume

Synchronous: `POST /api/chat` blocks while the turn loop drives hops. When an agent
returns `needs_input`, the loop stops and returns it; the endpoint stores the
turn id in the column it already owns:

```python
pending = {
    "correlation_id": "...",
    "agent": "reminder",
    "token": "<opaque, agent-owned>",
    "ask": {"kind": "confirm", "action": {...}},
}
```

`POST /api/chat/confirm` calls `loop.resume(correlation_id, decision)`, which
reloads the tree from `agent_states`, calls that agent's `resume(token, ...)`,
and carries on to the responder.

**The checkpointer is not involved in the tree.** It keeps doing exactly one
job: pausing and resuming a single agent's own graph. Two mechanisms, two
purposes.

## Idempotency

The loop owns at-most-once execution of confirmed writes, absorbing
`execution_ledger`.

**Constraint that must hold:** the key stays derived from the *action*, not from
the hop. A `message_id` changes when a hop is re-driven (a retried confirm, a
recovered turn), so keying on it would let the same write run twice. Keep
`action_id`'s uuid5-over-the-action-fingerprint derivation exactly as it is —
only the caller moves.

## Failure

An agent failure is a `failed` state in the tree. The loop does not retry; it
routes to the responder, which explains. The turn's HTTP response is still 200
with a reply — an error is a thing the user is told, not a stack trace.

## Phases

| | | reversible? |
|---|---|---|
| **1** ✅ | `AgentSpec`, `AgentResult`, `AgentMessage`, loop skeleton, `agent_states` + migration 0022. Nothing wired. | yes |
| **2** ✅ | Port `reminder` (smallest). Old handoff path still serves chat. | yes |
| **3** ✅ | Port `enrich`. | yes |
| **4** ✅ | Add `responder`. Loop drives reminder + enrich end to end behind a flag. | yes |
| **5** ✅ | `conversation` becomes a peer (as `finder`); endpoint calls the loop; the old handoff path deleted. | no |

Phase 5 was taken in pieces so each was reviewable on its own: the model router,
`read_state`, `finder`, the endpoint, then the cleanup. The cleanup removed
`agents/conversation/`, `agents/runtime/handoff_dispatch.py`,
`agents/runtime/specialist_registry.py`, `api/chat/`, `api/evals/` and
`HANDOFF_SPECIALISTS`/`MODE_AGENTS`; `tools/conversation/` became
`tools/finder/`, losing the two handoff tool specs.

`api/evals` went with it: it replayed turns through `conversation.evaluate_turn`,
which no longer exists. The `agent_evaluations` tables remain (migrations are
append-only), so an eval surface rebuilt on the farm can reuse them. The
`/eval` and `/eval_metrics` bot commands and `EVAL_ADMIN_TELEGRAM_IDS` are gone.

### The endpoint

`api/chat_v2/` is a section vertical of its own (`endpoints.py` / `helper.py` /
`db.py`) serving `/api/chat/v2` and `/api/chat/v2/confirm`. It was built
alongside v1 so the two could be swapped by a URL; v1 is now gone, and the
`_v2` in the folder and route names is the last trace of that — collapse it
back to `/api/chat` whenever it stops being useful as a marker.

Three things the loop does not do, which this section therefore does:

- **it keeps the transcript.** The loop returns no message list — the finder
  builds its own scratch messages and keeps them — so the section appends the
  user's message and the responder's reply. The thread becomes a clean record of
  what was said, with no tool calls in it, and prior turns reach the finder as
  `references={"messages": …}` because the thread belongs to the section, not to
  the farm.
- **it stores the turn handle.** `TurnOutcome.pending` goes into the same
  `chat_threads.pending` column v1 uses. The two shapes differ, so
  `helper.find_resumable` treats a `pending` without a `correlation_id` as
  nothing to confirm — written to tell v1's shape from v2's, and still the
  guard against a thread left mid-confirm by the old code. No migration.
- **it carries the question into the confirm.** `farm.resume` takes a message; a
  confirm has none, so the section reads the last user message back off the
  thread. The resumed hops and the responder's second reply need the request
  that started the turn to phrase anything about it.

`citations` is not on the v2 response. `TurnOutcome` carries no agent state, so
the finder's cited notes are not reachable from the endpoint yet — v1 still
serves chips, and inline `[[note:ID]]` markers work on both, since the client
fetches those by id. Closing that gap means either reading the finder hop's row
through `read_state` (no loop change) or putting each hop's state on the
outcome (a loop change), and it is still open.

### The finder

`agents/finder/` is the conversation controller as a peer — copied, then cut
down to what the farm does not already own:

- **no `handoff` node, no `approve` node.** The controller could call
  `perform_action` / `set_reminder` to route a write at the model's discretion;
  finder has neither tool and gets `READ_TOOL_SPECS` only. Which agent owns a
  write is the router's case-3 decision, so the one agent that named its peers
  no longer does.
- **no checkpointer.** With no interrupt, a hop runs start to finish, so there
  is no `resume`, no thread-scoped `graph_config`, and no retry of an unfinished
  run. The hop's durable record is its `agent_states` row.
- **no reply.** The answer goes into `AgentResult.state` as
  `{answer, citations, trace}`; the responder reaches it through `read_state`
  and does the speaking. Every cited note is reported as a `Ref("note", id)` —
  reading is not producing, so those say what the answer rested on.

What is left is `reason` + `act` over `tools/finder/` — the old
`tools/conversation/`, renamed when the controller went, minus the two handoff
tool specs.

Phase 4 is the checkpoint: if the loop cannot drive a two-hop turn (enrich
writes a note, reminder schedules it, responder explains both) without an agent
knowing about another, stop before Phase 5.

## Open risks

- **The responder adds a hop to every turn, including trivial ones.** A plain
  question now costs router + finder + responder where it used to cost one
  agent. The fallback template makes it safe, not fast. If it hurts, the answer
  is probably letting `finder` mark its own output as final-quality prose,
  which weakens the one-place rule.
- **`AGENT_ROUTER_ALWAYS` makes dev behave unlike production** by construction.
  That is the point, but it means a routing bug that only appears in the
  `entry_tools` fast path will not show up locally. Case 1–2 need their own
  (cheap, model-free) assertions.
- **Two idempotency scopes now coexist**: the loop's `action_id` ledger for
  confirmed writes, and the checkpointer for graph resume. A turn that fails
  between them — write committed, checkpoint not advanced — is the case worth
  testing hardest before Phase 5.
