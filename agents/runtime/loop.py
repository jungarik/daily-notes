"""The loop: it drives one turn across the agent farm.

It asks the router who runs next, hands that agent an `AgentRequest`, saves the
state that comes back, folds the result into the turn history, and repeats until
an agent needs the user or the responder has written the reply. Agents never name
each other; the loop never looks inside an agent's state or its resume token.

Which agent runs each hop is `agents/router/`'s decision, not this file's.
This module owns only the turn around it — pick, run, save, fold in, suspend
or finish — plus the pure helpers that turn needs: the ledger codec, the
action id,
and the two rules that keep the turn history trustworthy (an entry is derived
from a result rather than written by an agent, and each hop contributes its own
entry — except a resumed one, which supersedes the pause it answers).
"""

import json
import logging
import uuid

from agents.contracts import (
    AGENT_KIND,
    AgentRequest,
    AgentResult,
    AgentSpec,
    HistoryEntry,
    Ref,
    TurnOutcome,
    UserContext,
)

from agents.runtime.registry import ROUTER

logger = logging.getLogger(__name__)

DECLINED = "The user declined this action; it was not performed."


def generate_action_id(correlation_id: str, agent: str, tool_name: str, tool_args: dict) -> str:
    """A stable id for one confirmed write.

    Derived from the *write itself*, never from the hop: a `request_id` changes
    when a hop is re-driven (a retried confirm, a recovered turn), and keying on
    that would let the same write run twice. Argument order cannot change the id
    either — the fingerprint is sorted.
    """
    fingerprint = json.dumps({
        "correlation_id": correlation_id,
        "agent": agent,
        "name": tool_name,
        "args": tool_args,
    }, sort_keys=True, separators=(",", ":"), default=str)

    return str(uuid.uuid5(uuid.NAMESPACE_URL, fingerprint))


def encode(result: AgentResult) -> str:
    """An approved hop's outcome, as the durable string the ledger replays.

    Must not raise. It runs inside the ledger's claim, after the write has
    already happened, so an exception here would leave the action marked failed
    and lose the outcome of work that actually succeeded. A malformed ref is
    written out as-is and rejected later by `find_problems`.
    """
    return json.dumps({
        "status": result.status,
        "state": result.state,
        "produced": [
            {"kind": getattr(ref, "kind", None), "id": getattr(ref, "id", None)}
            if isinstance(ref, Ref) else ref
            for ref in result.produced
        ],
        "error": result.error,
    }, default=str)


def decode(stored: str) -> AgentResult:
    """Rebuild a result from the ledger. A record written by older code will not
    parse; it becomes a plain `done` carrying the text, which is what the ledger
    already promised its caller."""
    try:
        payload = json.loads(stored)
    except (TypeError, ValueError):
        return AgentResult(status="done", state={"detail": str(stored)})

    if not isinstance(payload, dict) or "status" not in payload:
        return AgentResult(status="done", state={"detail": str(stored)})

    return AgentResult(
        status=payload["status"],
        state=payload.get("state") or {},
        produced=tuple(
            Ref(kind=str(item.get("kind")), id=str(item.get("id")))
            for item in payload.get("produced") or []),
        error=payload.get("error"))


def find_problems(produced: object) -> list[str]:
    """Why this `produced` cannot become a history entry, or an empty list.

    The parameter is `object` on purpose. `AgentResult.produced` is *declared*
    `tuple[Ref, ...]`, but this is the trust boundary where an agent's promise is
    checked — annotating it `tuple[Ref, ...]` here would assert the very thing
    being verified, and a type checker would then call these branches dead.

    An *empty* list is valid: an agent that searched and found nothing genuinely
    produced nothing, and no rule here can tell that apart from an agent that
    forgot to report. That guard belongs in the agent's own tests.
    """
    if not isinstance(produced, (list, tuple)):
        return [f"produced must be a sequence, got {type(produced).__name__}"]

    found = []

    for position, ref in enumerate(produced):
        if not isinstance(ref, Ref):
            found.append(f"produced[{position}] is {type(ref).__name__}, not Ref")
            continue

        if not (isinstance(ref.kind, str) and ref.kind.strip()):
            found.append(f"produced[{position}].kind is empty")

        if not (isinstance(ref.id, str) and ref.id.strip()):
            found.append(f"produced[{position}].id is empty")

    return found


def merge_history(history: tuple[HistoryEntry, ...],
                  fresh: HistoryEntry) -> tuple[HistoryEntry, ...]:
    """`history` with this hop folded in — one entry per hop.

    An agent may run more than once in a turn (create a note, then link it), and
    each run is its own entry: collapsing them to one would hide the first from
    the router deciding what is left to do and from the responder writing the
    reply, which is the whole record they work from.

    The one entry that is replaced rather than appended is a `needs_input` from
    this same agent — the pause it is resuming. That is not a second hop, it is
    the same hop finishing, and leaving both would report a turn as still
    waiting on a user who already answered. `agent_states` keeps both rows
    either way; that is the audit record, and this is the routing view.
    """
    kept = tuple(item for item in history
                 if not (item.agent == fresh.agent and item.status == "needs_input"))

    return (*kept, fresh)


class Loop:
    """Drives one turn across the agent farm.

    It runs the loop — pick, run, save, fold in, suspend or finish — and owns
    only the two routing cases that need no model: the responder takes the hop
    when the turn is finishing, and a caller-supplied `entry_agent` names the
    first one outright. Both are this file's own state (`hops_left`, the
    unspent entry agent) rather than routing policy. Everything else is the
    router agent's choice, and it is an ordinary registered hop like any other.

    The store, ledger and registry arrive at construction because this is the
    impure top of the call stack — everything below it takes data and returns
    data.
    """

    def __init__(self,
                 store,
                 ledger,
                 registry,
                 max_hops: int = 4,
                 always_route: bool = False):
        self._store = store
        self._ledger = ledger
        self._registry = registry
        self._max_hops = max_hops
        self._always_route = always_route

    def run(self, message: str, context: UserContext, references: dict | None = None,
              entry_agent: str | None = None) -> TurnOutcome:
        """Run a fresh turn.

        The turn's owner travels in `context`, not beside it — one source of
        truth, so the row the store writes and the note an agent creates can
        never disagree about whose they are. `entry_agent` is the case-2
        shortcut: the agent a caller already knows should take the first hop,
        naming it outright so the turn spends no model call deciding. A name
        this farm does not have simply misses, and the router is asked.
        """
        return self._run_internal(
            correlation_id=str(uuid.uuid4()),
            message=message,
            context=context,
            references=references or {},
            history=(),
            causation_id=None,
            entry_agent=entry_agent)

    def resume(self, pending: dict, decision: dict, message: str, context: UserContext,
               references: dict | None = None) -> TurnOutcome:
        """Carry on a turn the user was asked about.

        A decline runs nothing — there is no write to make idempotent — so the
        agent's `resume` is called only on approval, and no agent implements
        decline handling.
        """
        correlation_id = pending["correlation_id"]
        agent = self._registry.get(pending["agent"])

        if decision.get("approve"):
            result = self._confirm(correlation_id, agent, pending, decision, context)
        else:
            result = AgentResult(status="done", state={"declined": True, "detail": DECLINED})

        found = find_problems(result.produced)

        if found:
            logger.error("agent %s reported invalid refs: %s", agent.name, found)
            result = AgentResult(
                status="failed",
                state=result.state,
                error=f"invalid produced: {'; '.join(found)}")

        state_id = self._store.save(
            correlation_id=correlation_id,
            causation_id=pending.get("state_id"),
            user_id=context["user_id"],
            agent=agent.name,
            status=result.status,
            produced=tuple(result.produced),
            state=result.state)

        # Read the earlier hops *before* saving this one. The store returns every
        # row now, so reading afterwards would hand back the row this method is
        # about to fold in explicitly and the confirmed hop would appear twice.
        merged_history = merge_history(self._store.read_history(correlation_id), HistoryEntry(
            agent=agent.name,
            status=result.status,
            produced=tuple(result.produced),
            error=result.error,
            state_id=state_id))

        return self._run_internal(
            correlation_id=correlation_id,
            message=message,
            context=context,
            references=references or {},
            history=merged_history,
            causation_id=state_id,
            entry_agent=None)

    def _confirm(self, correlation_id: str, agent: AgentSpec, pending: dict,
                   decision: dict, context: UserContext) -> AgentResult:
        """Run an approved write at most once, replaying the stored outcome if it
        already ran."""
        action = (pending.get("ask") or {}).get("action") or {}
        idempotency_action_id = generate_action_id(
            correlation_id,
            agent.name,
            action.get("name"),
            action.get("args"))

        return decode(self._ledger.execute_once(
            idempotency_action_id,
            context["user_id"],
            agent.name,
            action,
            lambda: encode(agent.resume(pending["token"], decision, context))))

    def _read_choice(self, result: AgentResult) -> AgentSpec | None:
        """The agent the router named, or the responder when it declined.

        The decision arrives as a `Ref(AGENT_KIND, name)` in `produced` — the
        router reports what it did exactly as every other agent does. Nothing
        produced means it found no one, and the responder still takes the hop
        so the turn ends with a reply rather than with silence.
        """
        for ref in result.produced:
            if ref.kind == AGENT_KIND:
                return self._registry.get(ref.id)

        return self._registry.find_responder()

    def _run_internal(self, correlation_id: str,
               message: str,
               context: UserContext,
               references: dict,
               history: tuple[HistoryEntry, ...],
               causation_id: str | None,
               entry_agent: str | None) -> TurnOutcome:
        # The router's own entries do not spend the budget: routing is free, so
        # a turn still gets `max_hops` agents that do work plus the reply.
        worked = sum(1 for entry in history if entry.agent != ROUTER)
        hops_left = self._max_hops - worked
        finishing = False
        failed = False
        pending = None
        reply = None

        while hops_left > 0:
            # Case 1. The turn is finishing — it asked the user, it broke, or
            # this is the last slot — so the responder takes the hop and no
            # decision is needed. A farm with no responder simply stops here.
            if finishing or hops_left <= 1:
                agent = self._registry.find_responder()

                if agent is None:
                    break
            else:
                # Case 2. A caller that already knows who should act names
                # them, and the hop costs no model call. Loop-local state, not
                # routing policy: whether the shortcut is still unspent, and
                # whether `always_route` is forcing every hop through the
                # router. A name nothing answers to is not a dead end — it
                # misses, and case 3 asks.
                agent = (None if entry_agent is None or self._always_route
                         else self._registry.find_by_name(entry_agent))
                entry_agent = None

            if agent is None:
                # Case 3. The router is an ordinary hop — it runs, it is saved,
                # and it lands in the history — and then its `produced` names
                # whoever runs next. Two agents per iteration, and only this
                # one costs a model call.
                # The whole roster, every hop — an agent that already ran is
                # still a candidate. A turn often needs the same agent twice
                # (create a note, then link it), and filtering by what had run
                # made that impossible: it left the router choosing between
                # whoever happened to be untouched rather than whoever fits.
                # What has run is context for the decision, not a constraint on
                # it, so it reaches the router in the history instead.
                candidates = self._registry.list_agents()
                router_agent = self._registry.find_router()

                if not candidates or router_agent is None:
                    # Nothing to choose between, so there is nothing to ask:
                    # the responder takes the hop and the turn ends with a
                    # reply. Skipping the call also skips the row — a router
                    # hop on the record should mean a decision was made.
                    agent = self._registry.find_responder()
                else:
                    # Only the agent's own call is guarded: a crash inside it is
                    # a failed state in the tree, while a loop bug building the
                    # request above is not an agent failure and must not be
                    # disguised as one.
                    try:
                        router_result = router_agent.start(AgentRequest(
                              request_id=str(uuid.uuid4()),
                              correlation_id=correlation_id,
                              causation_id=causation_id,
                              agent=router_agent.name,
                              message=message,
                              context=context,
                              references={**references, "candidates": candidates},
                              history=history,
                              hops_left=hops_left))
                    except Exception as exc:
                        logger.exception("agent %s failed on turn %s", router_agent.name,
                                         correlation_id)
                        router_result = AgentResult(status="failed", error=str(exc))

                    found = find_problems(router_result.produced)

                    if found:
                        logger.error("agent %s reported invalid refs: %s",
                                     router_agent.name, found)
                        router_result = AgentResult(
                            status="failed",
                            state=router_result.state,
                            error=f"invalid produced: {'; '.join(found)}")

                    # The row is saved before the entry is built: its id is what
                    # the entry carries, and that is the handle a later agent
                    # follows to `read_state`.
                    router_state_id = self._store.save(
                        correlation_id=correlation_id,
                        causation_id=causation_id,
                        user_id=context["user_id"],
                        agent=router_agent.name,
                        status=router_result.status,
                        produced=tuple(router_result.produced),
                        state=router_result.state)

                    history = merge_history(history, HistoryEntry(
                        agent=router_agent.name,
                        status=router_result.status,
                        produced=tuple(router_result.produced),
                        error=router_result.error,
                        state_id=router_state_id))
                    causation_id = router_state_id
                    agent = self._read_choice(router_result)

            if agent is None:
                break

            # Guarded, validated and saved exactly as the router hop above —
            # the router is an ordinary agent, so it gets no shortcut and no
            # special handling.
            try:
                result = agent.start(AgentRequest(
                  request_id=str(uuid.uuid4()),
                  correlation_id=correlation_id,
                  causation_id=causation_id,
                  agent=agent.name,
                  message=message,
                  context=context,
                  references=references,
                  history=history,
                  hops_left=hops_left))
            except Exception as exc:
                logger.exception("agent %s failed on turn %s", agent.name, correlation_id)
                result = AgentResult(status="failed", error=str(exc))

            found = find_problems(result.produced)

            if found:
                logger.error("agent %s reported invalid refs: %s", agent.name, found)
                result = AgentResult(
                    status="failed",
                    state=result.state,
                    error=f"invalid produced: {'; '.join(found)}")

            state_id = self._store.save(
                correlation_id=correlation_id,
                causation_id=causation_id,
                user_id=context["user_id"],
                agent=agent.name,
                status=result.status,
                produced=tuple(result.produced),
                state=result.state)

            history = merge_history(history, HistoryEntry(
                agent=agent.name,
                status=result.status,
                produced=tuple(result.produced),
                error=result.error,
                state_id=state_id))

            causation_id = state_id
            hops_left -= 1

            # How the turn ends is tracked here rather than read back off the
            # history, because the last entry is the reply, not the work.
            if result.status == "needs_input":
                pending = {
                    "correlation_id": correlation_id,
                    "agent": agent.name,
                    "token": result.token,
                    "ask": result.ask,
                    "state_id": state_id,
                }

            failed = failed or result.status == "failed"

            # One flag for every way a turn can be over: it asked the user, it
            # broke, or this was the last slot.
            finishing = finishing or result.status in ("needs_input", "failed")

            if result.reply is not None:
                # The user has been answered, so there is nothing left to do.
                # This — rather than a check that the responder already ran — is
                # what ends the loop: a confirm continues a turn whose history
                # *already* holds the reply given when it suspended, and still
                # owes a second one for the write it just made.
                reply = result.reply
                break

        return TurnOutcome(
            status="needs_input" if pending else "failed" if failed else "done",
            correlation_id=correlation_id,
            history=history,
            pending=pending,
            reply=reply)

