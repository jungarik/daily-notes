"""Broker for the Conversation → specialist handoff protocol.

Owns the whole plan → stage → approve → execute contract in one place: which
specialist serves a handoff tool and in which mode, how the typed contract is
built, how a planned action is staged for approval, and how an approved action
is executed exactly once through the idempotency ledger.

Graph nodes keep only their state shaping; adding a handoff is a route
registration in the composition root plus its tool spec.
"""

import logging
import uuid
from dataclasses import dataclass

from agents.contracts import handoff
from agents.runtime import execution_ledger

logger = logging.getLogger(__name__)

DECLINED = "The user declined this action; do not perform it. Acknowledge and continue."

NO_ACTION = "No concrete action could be determined."


@dataclass(frozen=True)
class HandoffRoute:
    """Which specialist serves a handoff tool, and in which planning mode."""

    agent: str
    mode: str


@dataclass(frozen=True)
class HandoffPlan:
    """The outcome of asking a specialist to plan one handoff.

    `action` is the concrete write awaiting approval; `error` is set when the
    specialist raised, which the caller can distinguish from "nothing to do".
    """

    route: HandoffRoute
    contract: dict
    action: dict | None = None
    error: str | None = None

    @property
    def planned(self) -> bool:
        return self.action is not None

    @property
    def tool_message(self) -> str:
        """What the model is told when no action came back."""
        if self.error:
            return f"{NO_ACTION} The specialist failed: {self.error}"

        return NO_ACTION


def _with_selection(action: dict, selection) -> dict:
    """For a select action (link_notes), replace its targets with the user's pick."""
    if selection is None or action.get("name") != "link_notes":
        return action

    chosen = []

    for value in selection:
        try:
            note_id = int(value)
        except (TypeError, ValueError):
            continue

        if note_id not in chosen:
            chosen.append(note_id)

    return {**action, "args": {**action.get("args", {}), "linked_note_ids": chosen}}


class HandoffBroker:
    """Routes handoff tool calls to specialists and owns their write contract.

    Specialists are resolved through the registry by name at call time, so the
    registry stays the single owner of the concrete instances.
    """

    def __init__(self, registry, ledger=execution_ledger):
        self._registry = registry
        self._ledger = ledger
        self._routes: dict[str, HandoffRoute] = {}

    def register(self, tool_name: str, agent: str, mode: str) -> None:
        self._routes[tool_name] = HandoffRoute(agent, mode)

    def route(self, tool_name: str) -> HandoffRoute:
        try:
            return self._routes[tool_name]
        except KeyError as exc:
            raise LookupError(f"Unknown handoff tool: {tool_name}") from exc

    def plan(self,
             tool_name: str,
             messages: list[dict],
             tool_args: dict,
             references: list[dict],
             ctx) -> HandoffPlan:
        """Ask the owning specialist for the single write this handoff implies."""
        route = self.route(tool_name)
        contract = handoff.build(
            messages,
            tool_args,
            references,
            ctx,
        )
        contract["resolved_entities"]["specialist_mode"] = route.mode

        try:
            action = self._registry.get(route.agent).plan_action(
                ctx.user_id,
                contract,
                ctx.now,
                ctx.tz,
                ctx.locale,
            )
        except Exception as exc:
            logger.exception(
                "handoff planning failed: tool=%s agent=%s user=%s",
                tool_name,
                route.agent,
                ctx.user_id,
            )

            return HandoffPlan(route, contract, error=str(exc))

        if not action:
            logger.info(
                "handoff produced no action: tool=%s mode=%s user=%s",
                tool_name,
                route.mode,
                ctx.user_id,
            )

            return HandoffPlan(route, contract)

        logger.info(
            "handing off to %s: %s user=%s",
            route.mode,
            action["name"],
            ctx.user_id,
        )

        return HandoffPlan(route, contract, action=action)

    def stage(self, tool_call_id: str, plan: HandoffPlan) -> dict:
        """Build the pending record an approval pause resumes from."""
        return {
            "action_id": str(uuid.uuid4()),
            "tool_call_id": tool_call_id,
            "agent": plan.route.agent,
            "action": plan.action,
            "summary": plan.action["summary"],
            "handoff": plan.contract,
        }

    def execute(self, pending: dict, ctx, selection=None) -> str:
        """Run an approved action exactly once through its owning specialist."""
        agent = pending.get("agent") or "enrich"
        specialist = self._registry.get(agent)
        action = _with_selection(pending["action"], selection)

        return self._ledger.execute_once(
            pending["action_id"],
            ctx.user_id,
            agent,
            action,
            lambda: specialist.execute_action(
                ctx.user_id,
                action,
                ctx.now,
                ctx.tz,
                ctx.locale,
            ),
        )
