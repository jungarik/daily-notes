"""Unit tests for the handoff broker's plan/stage/execute contract."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from agents.conversation.state import ConversationContext as ChatCtx
from agents.runtime import handoff_broker
from agents.runtime.handoff_broker import HandoffBroker, pending
from agents.runtime.specialist_registry import SpecialistRegistry

NOW = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)

ACTION = {
    "name": "set_note_path",
    "args": {"note_id": 4, "path": "Projects"},
    "summary": "Move note 4",
}


def build_broker(specialist, ledger=None):
    registry = SpecialistRegistry()
    registry.register("enrich", specialist)
    broker = HandoffBroker(registry, ledger or SimpleNamespace())
    broker.register("perform_action", "enrich", "enrich")
    broker.register("set_reminder", "enrich", "reminder")

    return broker


def ctx():
    return ChatCtx(7, NOW, tz=timezone.utc, locale="en")


class HandoffBrokerTests(unittest.TestCase):
    def test_plan_stamps_the_route_mode_and_returns_the_action(self):
        specialist = SimpleNamespace(plan_action=Mock(return_value=ACTION))
        broker = build_broker(specialist)

        plan = handoff_broker.plan(
            broker.route("set_reminder"),
            broker.registry,
            [{"role": "user", "content": "remind me tomorrow"}],
            {"instruction": "remind me tomorrow"},
            [],
            ctx(),
        )

        self.assertTrue(plan.planned)
        self.assertEqual(plan.action, ACTION)
        self.assertEqual(plan.route.mode, "reminder")
        self.assertEqual(plan.route.agent, "enrich")
        contract = specialist.plan_action.call_args.args[1]
        self.assertEqual(contract["resolved_entities"]["specialist_mode"], "reminder")

    def test_plan_without_an_action_is_not_planned(self):
        broker = build_broker(SimpleNamespace(plan_action=Mock(return_value=None)))

        plan = handoff_broker.plan(broker.route("perform_action"), broker.registry, [], {"instruction": "do a thing"}, [], ctx())

        self.assertFalse(plan.planned)
        self.assertIsNone(plan.error)
        self.assertEqual(plan.tool_message, "No concrete action could be determined.")

    def test_a_failing_specialist_is_reported_not_raised(self):
        specialist = SimpleNamespace(plan_action=Mock(side_effect=RuntimeError("boom")))
        broker = build_broker(specialist)

        plan = handoff_broker.plan(broker.route("perform_action"), broker.registry, [], {"instruction": "do a thing"}, [], ctx())

        self.assertFalse(plan.planned)
        self.assertEqual(plan.error, "boom")
        self.assertIn("boom", plan.tool_message)

    def test_an_unregistered_tool_is_rejected(self):
        broker = build_broker(SimpleNamespace(plan_action=Mock()))

        with self.assertRaises(LookupError):
            broker.route("unknown_tool")

    def test_stage_carries_the_agent_and_contract(self):
        specialist = SimpleNamespace(plan_action=Mock(return_value=ACTION))
        broker = build_broker(specialist)
        plan = handoff_broker.plan(broker.route("perform_action"), broker.registry, [], {"instruction": "move it"}, [], ctx())

        pending = pending("call-1", plan)

        self.assertEqual(pending["tool_call_id"], "call-1")
        self.assertEqual(pending["agent"], "enrich")
        self.assertEqual(pending["action"], ACTION)
        self.assertEqual(pending["summary"], "Move note 4")
        self.assertEqual(pending["handoff"], plan.contract)
        self.assertTrue(pending["action_id"])

    def test_execute_runs_the_action_through_the_ledger_once(self):
        specialist = SimpleNamespace(execute_action=Mock(return_value="moved"))
        ledger = SimpleNamespace(
            execute_once=Mock(side_effect=lambda *args: args[-1]()),
        )
        broker = build_broker(specialist, ledger)
        pending = {"action_id": "a-1", "agent": "enrich", "action": ACTION}

        result = handoff_broker.execute(pending, broker.registry, broker.ledger, ctx())

        self.assertEqual(result, "moved")
        self.assertEqual(ledger.execute_once.call_args.args[:4],
                         ("a-1", 7, "enrich", ACTION))

    def test_execute_applies_a_selection_to_a_link_action(self):
        specialist = SimpleNamespace(execute_action=Mock(return_value="linked"))
        ledger = SimpleNamespace(
            execute_once=Mock(side_effect=lambda *args: args[-1]()),
        )
        broker = build_broker(specialist, ledger)
        pending = {
            "action_id": "a-2",
            "agent": "enrich",
            "action": {
                "name": "link_notes",
                "args": {"note_id": 4, "linked_note_ids": [1, 2]},
                "summary": "Link note 4",
            },
        }

        handoff_broker.execute(pending, broker.registry, broker.ledger, ctx(), selection=["9", 9, "nope", 10])

        executed = specialist.execute_action.call_args.args[1]
        self.assertEqual(executed["args"]["linked_note_ids"], [9, 10])
        self.assertEqual(pending["action"]["args"]["linked_note_ids"], [1, 2])


if __name__ == "__main__":
    unittest.main()
