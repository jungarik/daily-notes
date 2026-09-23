"""The broker's routing, history and idempotency contracts.

Drives real `Broker` code against an in-memory store and hand-written agents, so
the turn tree, the entry-tool shortcut and the at-most-once guarantee are
exercised without a database, a model, or LangGraph.
"""

import unittest

from agents.broker import AgentRegistry, Broker, Ref, Router
from agents.broker.broker import (
    decode,
    encode,
    find_problems,
    generate_action_id,
    merge_history,
)
from agents.broker.contracts import AgentResult, AgentSpec, HistoryEntry, UserContext


class FakeStore:
    """The turn tree, in memory. Same surface the real `state_store` exposes."""

    def __init__(self):
        self.rows = []

    def save(self, correlation_id, causation_id, user_id, agent, status, produced, state):
        state_id = f"s{len(self.rows) + 1}"
        self.rows.append({
            "state_id": state_id,
            "correlation_id": correlation_id,
            "causation_id": causation_id,
            "user_id": user_id,
            "agent": agent,
            "status": status,
            "produced": tuple(produced),
            "state": state,
        })

        return state_id

    def read_history(self, correlation_id):
        latest = {}

        for row in self.rows:
            if row["correlation_id"] == correlation_id:
                latest[row["agent"]] = HistoryEntry(
                    agent=row["agent"],
                    status=row["status"],
                    produced=row["produced"],
                    state_id=row["state_id"])

        return tuple(latest.values())


class FakeLedger:
    """`execution_ledger` semantics: claim once, replay the stored result after."""

    def __init__(self):
        self.results = {}
        self.calls = 0

    def execute_once(self, key, user_id, agent, action, execute):
        if key in self.results:
            return self.results[key]

        self.calls += 1
        self.results[key] = execute()

        return self.results[key]


def _agent(name, result, **kwargs):
    return AgentSpec(
        name=name,
        description=f"{name} agent",
        start=lambda request: result,
        **kwargs)


def _broker(agents, router=None, router_always=False, **kwargs):
    """A broker over a fresh registry. `router` is the case-3 model seam."""
    registry = AgentRegistry()

    for agent in agents:
        registry.register(agent)

    return Broker(
        FakeStore(),
        FakeLedger(),
        Router(registry, select_model=router, always_ask_model=router_always),
        **kwargs), registry


CONTEXT: UserContext = {
    "user_id": 7,
    "now": "2026-09-18T09:00:00",
    "tz": "Europe/Kyiv",
    "locale": "en",
}


class RegistryTests(unittest.TestCase):
    def test_two_agents_cannot_claim_the_same_entry_tool(self):
        registry = AgentRegistry()
        registry.register(_agent("a", AgentResult("done"), entry_tools=("set_reminder",)))

        with self.assertRaises(ValueError):
            registry.register(_agent("b", AgentResult("done"), entry_tools=("set_reminder",)))

    def test_duplicate_agent_name_is_rejected(self):
        registry = AgentRegistry()
        registry.register(_agent("a", AgentResult("done")))

        with self.assertRaises(ValueError):
            registry.register(_agent("a", AgentResult("done")))

    def test_may_read_honours_the_wildcard(self):
        registry = AgentRegistry()
        registry.register(_agent("responder", AgentResult("done"), may_read=("*",)))
        registry.register(_agent("reminder", AgentResult("done"), may_read=("conversation",)))

        self.assertTrue(registry.may_read("responder", "reminder"))
        self.assertTrue(registry.may_read("reminder", "conversation"))
        self.assertFalse(registry.may_read("reminder", "responder"))


class HistoryTests(unittest.TestCase):
    def test_empty_produced_is_valid(self):
        self.assertEqual([], find_problems(()))

    def test_a_blank_kind_is_rejected(self):
        self.assertTrue(find_problems([Ref(kind="  ", id="1")]))

    def test_a_non_ref_is_rejected(self):
        self.assertTrue(find_problems([{"kind": "note", "id": "1"}]))

    def test_one_agent_keeps_one_entry(self):
        paused = HistoryEntry("reminder", "needs_input")
        finished = HistoryEntry("reminder", "done", produced=(Ref("reminder", "9"),))
        merged = merge_history((HistoryEntry("enrich", "done"), paused), finished)

        self.assertEqual(["enrich", "reminder"], [item.agent for item in merged])
        self.assertEqual(finished, merged[-1])


class RouterTests(unittest.TestCase):
    """The routing policy on its own, with no broker and no turn."""

    def setUp(self):
        self.registry = AgentRegistry()
        self.registry.register(
            _agent("reminder", AgentResult("done"), entry_tools=("set_reminder",)))
        self.registry.register(_agent("enrich", AgentResult("done")))

    def test_an_entry_tool_resolves_the_hop_with_no_model_call(self):
        asked = []
        router = Router(self.registry, select_model=lambda *args: asked.append(1))

        agent = router.select_agent("remind me", (), "set_reminder")

        self.assertEqual("reminder", agent.name)
        self.assertEqual([], asked)

    def test_no_model_seam_means_the_turn_runs_out_of_moves(self):
        router = Router(self.registry)

        self.assertIsNone(router.select_agent("go", (), None))

    def test_always_ask_model_skips_the_entry_tool(self):
        router = Router(
            self.registry,
            select_model=lambda candidates, message, history: "enrich",
            always_ask_model=True)

        agent = router.select_agent("remind me", (), "set_reminder")

        self.assertEqual("enrich", agent.name)

    def test_a_spent_agent_is_not_offered_as_a_candidate(self):
        seen = {}
        router = Router(
            self.registry,
            select_model=lambda candidates, message, history: (
                seen.update(candidates=candidates) or candidates[0]["name"]))

        router.select_agent("go", (HistoryEntry("reminder", "done"),), None)

        self.assertEqual(["enrich"], [item["name"] for item in seen["candidates"]])

    def test_no_candidates_left_short_circuits_the_model(self):
        asked = []
        router = Router(self.registry, select_model=lambda *args: asked.append(1))
        spent = (HistoryEntry("reminder", "done"), HistoryEntry("enrich", "done"))

        self.assertIsNone(router.select_agent("go", spent, None))
        self.assertEqual([], asked, "no point asking a model with nothing to choose")

    def test_a_model_declining_ends_the_turn(self):
        router = Router(self.registry, select_model=lambda *args: None)

        self.assertIsNone(router.select_agent("go", (), None))

    def test_get_agent_resolves_a_suspended_turn_by_name(self):
        router = Router(self.registry)

        self.assertEqual("reminder", router.get_agent("reminder").name)

    def test_get_agent_raises_on_a_name_that_no_longer_exists(self):
        """A suspended turn naming a retired agent is a deploy mistake; it must
        surface here rather than as a `None` three frames later."""
        router = Router(self.registry)

        with self.assertRaises(LookupError):
            router.get_agent("retired")


class RoutingTests(unittest.TestCase):
    def test_an_entry_tool_routes_without_the_router(self):
        called = []
        broker, _ = _broker(
            [_agent("reminder", AgentResult("done"), entry_tools=("set_reminder",))],
            router=lambda roster, message, history: called.append(1))

        outcome = broker.start("remind me tomorrow", CONTEXT, entry_tool="set_reminder")

        self.assertEqual("done", outcome.status)
        self.assertEqual(["reminder"], [item.agent for item in outcome.history])
        self.assertEqual([], called)

    def test_router_always_ignores_the_entry_tool(self):
        seen = {}

        def router(roster, message, history):
            seen["roster"] = roster

            return "reminder"

        broker, _ = _broker(
            [_agent("reminder", AgentResult("done"), entry_tools=("set_reminder",))],
            router=router,
            router_always=True)

        broker.start("remind me tomorrow", CONTEXT, entry_tool="set_reminder")

        self.assertEqual([{"name": "reminder", "description": "reminder agent"}],
                         seen["roster"])

    def test_an_unknown_entry_tool_ends_the_turn(self):
        broker, _ = _broker([_agent("reminder", AgentResult("done"))])

        outcome = broker.start("hello", CONTEXT, entry_tool="nonesuch")

        self.assertEqual((), outcome.history)

    def test_the_router_never_sees_an_agent_that_already_ran(self):
        seen = []

        def router(candidates, message, history):
            seen.append([item["name"] for item in candidates])

            return candidates[0]["name"]

        broker, _ = _broker(
            [_agent("a", AgentResult("done")), _agent("b", AgentResult("done"))],
            router=router)

        broker.start("go", CONTEXT)

        self.assertEqual([["a", "b"], ["b"]], seen, "a spent agent is not a candidate")

    def test_the_hop_bound_stops_a_farm_larger_than_the_budget(self):
        broker, _ = _broker(
            [_agent(name, AgentResult("done")) for name in "abcde"],
            router=lambda candidates, message, history: candidates[0]["name"],
            max_hops=2)

        outcome = broker.start("go", CONTEXT)

        self.assertEqual(2, len(outcome.history))


class TurnTreeTests(unittest.TestCase):
    def test_each_hop_is_caused_by_the_one_before_it(self):
        store = FakeStore()
        registry = AgentRegistry()
        registry.register(_agent("a", AgentResult("done")))
        registry.register(_agent("b", AgentResult("done")))
        order = iter(["a", "b", None])
        broker = Broker(store, FakeLedger(),
                        Router(registry, select_model=lambda *args: next(order)),
                        max_hops=4)

        broker.start("go", CONTEXT)

        self.assertEqual([None, "s1"], [row["causation_id"] for row in store.rows])
        self.assertEqual(1, len({row["correlation_id"] for row in store.rows}))

    def test_the_owner_comes_from_the_context_and_nowhere_else(self):
        """One source of truth: the row the store writes and the note an agent
        creates cannot disagree about whose turn this is."""
        store = FakeStore()
        registry = AgentRegistry()
        seen = []
        registry.register(AgentSpec(
            name="reminder",
            description="",
            start=lambda request: seen.append(request.context["user_id"]) or AgentResult("done"),
            entry_tools=("set_reminder",)))
        broker = Broker(store, FakeLedger(), Router(registry))

        broker.start("go", {**CONTEXT, "user_id": 42}, entry_tool="set_reminder")

        self.assertEqual([42], seen)
        self.assertEqual(42, store.rows[0]["user_id"])

    def test_a_context_without_an_owner_fails_loudly(self):
        broker, _ = _broker([_agent("a", AgentResult("done"), entry_tools=("t",))])

        with self.assertRaises(KeyError):
            broker.start("go", {"locale": "en"}, entry_tool="t")

    def test_references_reach_the_agent_separately_from_context(self):
        seen = {}
        registry = AgentRegistry()
        registry.register(AgentSpec(
            name="a",
            description="",
            start=lambda request: seen.update(
                refs=request.references, ctx=request.context) or AgentResult("done"),
            entry_tools=("t",)))
        broker = Broker(FakeStore(), FakeLedger(), Router(registry))

        broker.start("go", CONTEXT, references={"citations": [{"note_id": 3}]}, entry_tool="t")

        self.assertEqual([{"note_id": 3}], seen["refs"]["citations"])
        self.assertNotIn("citations", seen["ctx"], "the shared context stays clock-only")

    def test_an_agent_that_raises_becomes_a_failed_state(self):
        def explode(request):
            raise RuntimeError("boom")

        registry = AgentRegistry()
        registry.register(AgentSpec(
            name="reminder", description="", start=explode, entry_tools=("set_reminder",)))
        store = FakeStore()
        broker = Broker(store, FakeLedger(), Router(registry))

        outcome = broker.start("go", CONTEXT, entry_tool="set_reminder")

        self.assertEqual("failed", outcome.status)
        self.assertEqual("boom", outcome.history[-1].error)
        self.assertEqual("failed", store.rows[-1]["status"])

    def test_invalid_refs_are_downgraded_to_a_failure(self):
        broker, _ = _broker([_agent(
            "reminder",
            AgentResult("done", produced=({"kind": "note", "id": "1"},)),
            entry_tools=("set_reminder",))])

        outcome = broker.start("go", CONTEXT, entry_tool="set_reminder")

        self.assertEqual("failed", outcome.status)
        self.assertIn("produced[0]", outcome.history[-1].error)


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.ask = {"kind": "confirm", "action": {"name": "create_reminder", "args": {"t": 1}}}
        self.registry = AgentRegistry()
        self.registry.register(AgentSpec(
            name="reminder",
            description="",
            start=lambda request: AgentResult(
                "needs_input", ask=self.ask, token="tok", state={"planned": True}),
            resume=lambda token, decision, context: AgentResult(
                "done", produced=(Ref("reminder", "42"),), state={"ran": True}),
            entry_tools=("set_reminder",)))
        self.store = FakeStore()
        self.ledger = FakeLedger()
        self.broker = Broker(self.store, self.ledger, Router(self.registry))

    @unittest.expectedFailure
    def test_invalid_refs_on_the_resume_path_are_also_downgraded(self):
        """KNOWN GAP: the two paths disagree about the same bad input.

        On the resume path the result goes through `encode`/`decode` inside the
        ledger before `find_problems` sees it, and `decode` rebuilds any
        `{"kind", "id"}` mapping into a real `Ref`. So a malformed `produced`
        that `_drive` rejects is silently normalised here and recorded as
        `done`. Marked expected-failure so the suite stays green and flags
        itself the moment this is fixed.
        """
        registry = AgentRegistry()
        registry.register(AgentSpec(
            name="reminder",
            description="",
            start=lambda request: AgentResult(
                "needs_input", ask=self.ask, token="tok"),
            resume=lambda token, decision, context: AgentResult(
                "done", produced=({"kind": "note", "id": "1"},)),
            entry_tools=("set_reminder",)))
        store = FakeStore()
        broker = Broker(store, FakeLedger(), Router(registry))
        paused = broker.start("remind me", CONTEXT, entry_tool="set_reminder")

        outcome = broker.resume(paused.pending, {"approve": True}, "x", CONTEXT)

        self.assertEqual("failed", outcome.status)
        self.assertIn("produced[0]", outcome.history[-1].error)
        self.assertEqual("failed", store.rows[-1]["status"])

    def test_the_resume_row_records_the_same_fields_as_a_drive_row(self):
        """Both copies must write the same columns; a field added to one and
        forgotten in the other shows up here."""
        paused = self.broker.start("remind me", CONTEXT, entry_tool="set_reminder")
        self.broker.resume(paused.pending, {"approve": True}, "x", CONTEXT)

        self.assertEqual(
            set(self.store.rows[0]),
            set(self.store.rows[1]),
            "the drive and resume save calls disagree about the row shape")
        self.assertEqual(7, self.store.rows[1]["user_id"])
        self.assertEqual("reminder", self.store.rows[1]["agent"])

    def test_a_pause_returns_pending_the_section_can_store(self):
        outcome = self.broker.start("remind me", CONTEXT, entry_tool="set_reminder")

        self.assertEqual("needs_input", outcome.status)
        self.assertEqual("reminder", outcome.pending["agent"])
        self.assertEqual("tok", outcome.pending["token"])
        self.assertEqual(outcome.correlation_id, outcome.pending["correlation_id"])

    def test_approval_runs_the_write_and_reports_what_it_made(self):
        paused = self.broker.start("remind me", CONTEXT, entry_tool="set_reminder")

        outcome = self.broker.resume(paused.pending, {"approve": True}, "remind me", CONTEXT)

        self.assertEqual("done", outcome.status)
        self.assertEqual((Ref("reminder", "42"),), outcome.history[-1].produced)
        self.assertEqual(1, len(outcome.history), "a paused agent keeps one history entry")

    def test_a_replayed_confirm_does_not_write_twice(self):
        paused = self.broker.start("remind me", CONTEXT, entry_tool="set_reminder")

        first = self.broker.resume(paused.pending, {"approve": True}, "x", CONTEXT)
        second = self.broker.resume(paused.pending, {"approve": True}, "x", CONTEXT)

        self.assertEqual(1, self.ledger.calls)
        self.assertEqual(first.history[-1].produced, second.history[-1].produced)

    def test_a_decline_runs_nothing(self):
        paused = self.broker.start("remind me", CONTEXT, entry_tool="set_reminder")

        outcome = self.broker.resume(paused.pending, {"approve": False}, "x", CONTEXT)

        self.assertEqual(0, self.ledger.calls)
        self.assertEqual("done", outcome.status)
        self.assertEqual((), outcome.history[-1].produced)

    def test_the_history_entry_points_at_the_state_it_summarises(self):
        """Without `state_id` an agent is told a hop happened but has no handle
        to pass to `read_state`."""
        paused = self.broker.start("remind me", CONTEXT, entry_tool="set_reminder")

        entry = paused.history[-1]

        self.assertEqual(self.store.rows[-1]["state_id"], entry.state_id)

    def test_the_entry_follows_the_latest_row_after_a_confirm(self):
        paused = self.broker.start("remind me", CONTEXT, entry_tool="set_reminder")

        outcome = self.broker.resume(paused.pending, {"approve": True}, "x", CONTEXT)

        self.assertEqual("s2", outcome.history[-1].state_id, "not the paused row")

    def test_both_hops_stay_in_the_tree(self):
        paused = self.broker.start("remind me", CONTEXT, entry_tool="set_reminder")
        self.broker.resume(paused.pending, {"approve": True}, "x", CONTEXT)

        self.assertEqual(["needs_input", "done"], [row["status"] for row in self.store.rows])
        self.assertEqual("s1", self.store.rows[1]["causation_id"])


class ActionIdTests(unittest.TestCase):
    def test_argument_order_does_not_change_the_id(self):
        self.assertEqual(
            generate_action_id("turn-1", "reminder", "create_reminder",
                      {"text": "x", "remind_at": "2026-01-01"}),
            generate_action_id("turn-1", "reminder", "create_reminder",
                      {"remind_at": "2026-01-01", "text": "x"}))

    def test_different_arguments_key_a_different_id(self):
        self.assertNotEqual(
            generate_action_id("turn-1", "reminder", "create_reminder", {"t": 1}),
            generate_action_id("turn-1", "reminder", "create_reminder", {"t": 2}))

    def test_a_different_tool_keys_a_different_id(self):
        self.assertNotEqual(
            generate_action_id("turn-1", "reminder", "create_reminder", {"t": 1}),
            generate_action_id("turn-1", "reminder", "cancel_reminder", {"t": 1}))


class LedgerCodecTests(unittest.TestCase):
    def test_a_result_survives_a_round_trip(self):
        result = AgentResult("done", state={"a": 1}, produced=(Ref("note", "5"),))

        self.assertEqual(result, decode(encode(result)))

    def test_a_record_from_older_code_still_reads(self):
        restored = decode("the reminder was created")

        self.assertEqual("done", restored.status)
        self.assertEqual("the reminder was created", restored.state["detail"])


if __name__ == "__main__":
    unittest.main()
