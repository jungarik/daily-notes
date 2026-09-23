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
from a result rather than written by an agent, and one agent contributes exactly
one entry however many times it ran).
"""

import json
import logging
import uuid

from agents.contracts import (
    AgentRequest,
    AgentResult,
    AgentSpec,
    HistoryEntry,
    Ref,
    TurnOutcome,
    UserContext,
)

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
    """`history` with this hop folded in — one agent, one entry.

    A paused agent's `needs_input` entry is replaced by its outcome when it
    resumes, so the router's "do not route to an agent that already ran" rule
    needs no special case for confirmation. `agent_states` still keeps both rows;
    that is the audit record, and this is the routing view.
    """
    kept = tuple(item for item in history if item.agent != fresh.agent)

    return (*kept, fresh)


class Loop:
    """Drives one turn across the agent farm.

    It runs the loop — pick, run, save, fold in, suspend or finish — and owns no
    routing policy of its own: `router.select_agent` decides each hop. So a new
    routing rule changes `router.py` and this file not at all.

    The store, ledger and router arrive at construction because this is the
    impure top of the call stack — everything below it takes data and returns
    data.
    """

    def __init__(self,
                 store,
                 ledger,
                 router,
                 max_hops: int = 4):
        self._store = store
        self._ledger = ledger
        self._router = router
        self._max_hops = max_hops

    def start(self, message: str, context: UserContext, references: dict | None = None,
              entry_tool: str | None = None) -> TurnOutcome:
        """Run a fresh turn.

        The turn's owner travels in `context`, not beside it — one source of
        truth, so the row the store writes and the note an agent creates can
        never disagree about whose they are. `entry_tool` is the case-2
        shortcut: the tool name the previous model call already chose, if there
        was one.
        """
        return self._run(
            correlation_id=str(uuid.uuid4()),
            message=message,
            context=context,
            references=references or {},
            history=(),
            causation_id=None,
            entry_tool=entry_tool)

    def resume(self, pending: dict, decision: dict, message: str, context: UserContext,
               references: dict | None = None) -> TurnOutcome:
        """Carry on a turn the user was asked about.

        A decline runs nothing — there is no write to make idempotent — so the
        agent's `resume` is called only on approval, and no agent implements
        decline handling.
        """
        correlation_id = pending["correlation_id"]
        agent = self._router.get_agent(pending["agent"])

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

        newHistory = merge_history(self._store.read_history(correlation_id), HistoryEntry(
            agent=agent.name,
            status=result.status,
            produced=tuple(result.produced),
            error=result.error,
            state_id=state_id))

        return self._run(
            correlation_id=correlation_id,
            message=message,
            context=context,
            references=references or {},
            history=newHistory,
            causation_id=state_id,
            entry_tool=None)

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

    def _run(self, correlation_id: str,
               message: str,
               context: UserContext,
               references: dict,
               history: tuple[HistoryEntry, ...],
               causation_id: str | None,
               entry_tool: str | None) -> TurnOutcome:
        user_id = context["user_id"]
        hops_left = self._max_hops - len(history)
        finishing = False
        failed = False
        pending = None
        reply = None

        while hops_left > 0:
            agent = self._router.select_agent(
                message,
                history,
                entry_tool,
                force_responder=finishing or hops_left <= 1)

            if agent is None:
                break

            entry_tool = None
            request = AgentRequest(
                request_id=str(uuid.uuid4()),
                correlation_id=correlation_id,
                causation_id=causation_id,
                agent=agent.name,
                message=message,
                context=context,
                references=references,
                history=history,
                hops_left=hops_left)

            # Only the agent's own call is guarded: a crash inside it is a failed
            # state in the tree, while a loop bug building the request above is
            # not an agent failure and must not be disguised as one.
            try:
                result = agent.start(request)
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

            # The row is saved before the entry is built: its id is what the
            # entry carries, and that is the handle a later agent follows to
            # `read_state`.
            state_id = self._store.save(
                correlation_id=correlation_id,
                causation_id=causation_id,
                user_id=user_id,
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
            # broke, or this was the last slot. The router needs no more than
            # that, and never inspects a status itself.
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

