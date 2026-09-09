"""Broker for the Conversation → specialist handoff protocol.

Owns the whole plan → stage → approve → execute contract in one place: which
specialist serves a handoff tool and in which mode, how the typed contract is
built, how a planned action is staged for approval, and how an approved action
is executed exactly once through the idempotency ledger.

Graph nodes keep only their state shaping; adding a handoff is a route
registration in the composition root plus its tool spec.
"""

import json
import logging
import uuid
from dataclasses import dataclass

from agents.contracts.handoff import HandoffContract
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

class HandoffBroker:
    """Holds the handoff routing table plus the shared registry/ledger.

    Route resolution lives here; the plan/execute functions are free-standing and
    take a resolved route and the registry/ledger (exposed as getters), so they
    never reach into broker internals.
    """

    def __init__(self, registry, ledger=execution_ledger):
        self._registry = registry
        self._ledger = ledger
        self._routes: dict[str, HandoffRoute] = {}

    @property
    def registry(self):
        return self._registry

    @property
    def ledger(self):
        return self._ledger

    def register(self, tool_name: str, agent: str, mode: str) -> None:
        self._routes[tool_name] = HandoffRoute(agent, mode)

    def route(self, tool_name: str) -> HandoffRoute:
        try:
            return self._routes[tool_name]
        except KeyError as exc:
            raise LookupError(f"Unknown handoff tool: {tool_name}") from exc


def _tool_context(messages: list[dict]) -> tuple[list[int], list[dict]]:
    ids, names, results = [], {}, []
    for message in messages[-16:]:
        for tool_call in message.get("tool_calls") or []:
            names[tool_call.get("id")] = (tool_call.get("function") or {}).get("name")
            raw = (tool_call.get("function") or {}).get("arguments") or "{}"
            try:
                args = raw if isinstance(raw, dict) else json.loads(raw)
            except Exception:
                args = {}
            note_ids = args.get("note_ids") or []
            if not isinstance(note_ids, list):
                note_ids = [note_ids]
            values = [args.get("note_id"), *note_ids]
            for value in values:
                try:
                    ids.append(int(value))
                except (TypeError, ValueError):
                    pass
        if message.get("role") != "tool":
            continue
        tool_name = names.get(message.get("tool_call_id"))
        content = str(message.get("content") or "")
        results.append({"tool": tool_name, "content": content[:1000]})
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = None
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if not isinstance(item, dict):
                continue
            value = item.get("note_id")
            if value is None and tool_name in {"get_note", "neighbors"}:
                value = item.get("id")
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                pass
    return ids, results[-5:]


def _conversation_summary(messages: list[dict], limit: int = 4000) -> str:
    lines = []
    for message in messages[-16:]:
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant"} or not content:
            continue
        lines.append(f"{role}: {' '.join(str(content).split())}")
    summary = "\n".join(lines)
    return summary[-limit:]


def _build_contract(messages: list[dict], tool_args: dict, citations: list[dict], ctx) -> HandoffContract:
    """Build ordered references from explicit args, prior tools, and citations."""
    ids = []
    for value in tool_args.get("referenced_note_ids") or []:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            pass
    tool_note_ids, tool_results = _tool_context(messages)
    ids.extend(tool_note_ids)
    ids.extend(item["note_id"] for item in citations if item.get("note_id") is not None)
    ordered_ids = list(dict.fromkeys(ids))
    cited = [{"note_id": int(item["note_id"]), "title": item.get("title") or "note"}
             for item in citations if item.get("note_id") is not None]
    resolved = dict(tool_args.get("resolved_entities") or {})
    resolved.update(
        last_note_id=ordered_ids[-1] if ordered_ids else None,
        ordinal_note_ids=ordered_ids,
        referenced_notes=cited,
        recent_tool_results=tool_results,
    )
    now = ctx.now.isoformat() if hasattr(ctx.now, "isoformat") else str(ctx.now or "")
    return {
        "instruction": str(tool_args.get("instruction") or "").strip(),
        "conversation_summary": _conversation_summary(messages),
        "referenced_note_ids": ordered_ids,
        "citations": cited,
        "resolved_entities": resolved,
        "locale": ctx.locale,
        "timezone": str(ctx.tz) if ctx.tz is not None else None,
        "now": now or None,
    }


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


def pending(tool_call_id: str, plan: HandoffPlan) -> dict:
    """Build the pending record an approval pause resumes from."""
    return {
        "action_id": str(uuid.uuid4()),
        "tool_call_id": tool_call_id,
        "agent": plan.route.agent,
        "action": plan.action,
        "summary": plan.action["summary"],
        "handoff": plan.contract,
    }


def plan(route: HandoffRoute,
         registry,
         messages: list[dict],
         tool_args: dict,
         references: list[dict],
         ctx) -> HandoffPlan:
    """Ask the specialist behind a resolved route for the single write it implies."""
    contract = _build_contract(
        messages,
        tool_args,
        references,
        ctx,
    )
    contract["resolved_entities"]["specialist_mode"] = route.mode

    try:
        action = registry.get(route.agent).plan_action(
            ctx.user_id,
            contract,
            ctx.now,
            ctx.tz,
            ctx.locale,
        )
    except Exception as exc:
        logger.exception(
            "handoff planning failed: agent=%s mode=%s user=%s",
            route.agent,
            route.mode,
            ctx.user_id,
        )

        return HandoffPlan(route, contract, error=str(exc))

    if not action:
        logger.info(
            "handoff produced no action: agent=%s mode=%s user=%s",
            route.agent,
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


def execute(pending: dict, registry, ledger, ctx, selection=None) -> str:
    """Run an approved action exactly once through its owning specialist."""
    agent = pending.get("agent") or "enrich"
    specialist = registry.get(agent)
    action = _with_selection(pending["action"], selection)

    return ledger.execute_once(
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
