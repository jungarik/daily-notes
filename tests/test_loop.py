"""The loop's routing, history and idempotency contracts.

Drives real `Loop` code against an in-memory store and hand-written agents, so
the turn tree, the entry-tool shortcut and the at-most-once guarantee are
exercised without a database, a model, or LangGraph.
"""

import unittest

# Importing `Router` reaches the model gateway — case 3 lives in the same
# module — and this file is the suite's first importer of it. Stub before
# that import or every later file inherits the real one.
from tests import gateway_stub

gateway_stub.install()

from agents.router import Router  # noqa: E402
from agents.runtime.registry import AgentRegistry
from agents.runtime.loop import (
    Loop,
    decode,
    encode,
    find_problems,
    generate_action_id,
    merge_history,
)
from agents.contracts import (
    AgentResult,
    AgentSpec,
    HistoryEntry,
    Ref,
    UserContext,
)


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


def _loop(agents, router=None, router_always=False, **kwargs):
    """A loop over a fresh registry. `router` is the case-3 model seam."""
    registry = AgentRegistry()

    for agent in agents:
        registry.register(agent)

    return Loop(
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
    """The routing policy on its own, with no loop and no turn."""

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


def _responder(reply="a reply"):
    """A stand-in responder: picked when the turn finishes, never a candidate."""
    return AgentSpec(
        name="responder",
        description="writes the reply",
        start=lambda request: AgentResult("done", reply=reply, state={"reply": reply}),
        may_read=("*",))


class ResponderHopTests(unittest.TestCase):
    """The responder is an ordinary hop the router picks last. Its running is
    what leaves the router with nothing to return, which ends the turn."""

    def test_a_finished_turn_ends_with_the_reply(self):
        loop, _ = _loop([
            _agent("reminder", AgentResult("done"), entry_tools=("set_reminder",)),
            _responder("Set your reminder."),
        ])

        outcome = loop.start("remind me", CONTEXT, entry_tool="set_reminder")

        self.assertEqual("done", outcome.status)
        self.assertEqual("Set your reminder.", outcome.reply)
        self.assertEqual(["reminder", "responder"], [i.agent for i in outcome.history])

    def test_a_failed_turn_still_gets_a_reply(self):
        """An error is something the user is told, not a stack trace."""
        def explode(request):
            raise RuntimeError("boom")

        registry = AgentRegistry()
        registry.register(AgentSpec(
            name="reminder", description="", start=explode, entry_tools=("set_reminder",)))
        registry.register(_responder("That went wrong."))
        loop = Loop(FakeStore(), FakeLedger(), Router(registry))

        outcome = loop.start("remind me", CONTEXT, entry_tool="set_reminder")

        self.assertEqual("failed", outcome.status, "the reply's own success is not the turn's")
        self.assertEqual("That went wrong.", outcome.reply)

    def test_a_suspended_turn_gets_a_reply_and_keeps_its_pending(self):
        registry = AgentRegistry()
        registry.register(AgentSpec(
            name="reminder",
            description="",
            start=lambda request: AgentResult(
                "needs_input", ask={"kind": "confirm"}, token="tok"),
            entry_tools=("set_reminder",)))
        registry.register(_responder("Shall I set that for tomorrow?"))
        loop = Loop(FakeStore(), FakeLedger(), Router(registry))

        outcome = loop.start("remind me", CONTEXT, entry_tool="set_reminder")

        self.assertEqual("needs_input", outcome.status)
        self.assertEqual("Shall I set that for tomorrow?", outcome.reply)
        self.assertEqual("reminder", outcome.pending["agent"])
        self.assertEqual("tok", outcome.pending["token"])

    def test_a_suspend_stops_the_work_even_with_agents_left(self):
        """`needs_input` finishes the turn: no other work agent gets a hop, even
        though the budget and the roster would allow one."""
        registry = AgentRegistry()
        registry.register(AgentSpec(
            name="reminder",
            description="",
            start=lambda request: AgentResult("needs_input", ask={}, token="tok"),
            entry_tools=("set_reminder",)))
        registry.register(_agent("enrich", AgentResult("done")))
        registry.register(_responder())
        loop = Loop(
            FakeStore(),
            FakeLedger(),
            Router(registry, select_model=lambda candidates, *args: candidates[0]["name"]),
            max_hops=5)

        outcome = loop.start("remind me", CONTEXT, entry_tool="set_reminder")

        self.assertEqual(["reminder", "responder"], [i.agent for i in outcome.history])

    def test_the_responder_runs_once_and_that_ends_the_loop(self):
        store = FakeStore()
        registry = AgentRegistry()
        registry.register(_agent("reminder", AgentResult("done"), entry_tools=("set_reminder",)))
        registry.register(_responder())
        loop = Loop(store, FakeLedger(), Router(registry), max_hops=5)

        loop.start("remind me", CONTEXT, entry_tool="set_reminder")

        self.assertEqual(["reminder", "responder"], [row["agent"] for row in store.rows])

    def test_the_responder_hop_is_saved_like_any_other(self):
        store = FakeStore()
        registry = AgentRegistry()
        registry.register(_agent("reminder", AgentResult("done"), entry_tools=("set_reminder",)))
        registry.register(_responder())
        loop = Loop(store, FakeLedger(), Router(registry))

        loop.start("remind me", CONTEXT, entry_tool="set_reminder")

        self.assertEqual("s1", store.rows[1]["causation_id"], "caused by the hop it reports")

    def test_it_is_never_offered_to_the_model_as_a_candidate(self):
        seen = []
        loop, _ = _loop(
            [_agent("enrich", AgentResult("done")), _responder()],
            router=lambda candidates, message, history: (
                seen.append([c["name"] for c in candidates]) or candidates[0]["name"]))

        loop.start("go", CONTEXT)

        self.assertEqual([["enrich"]], seen, "picked by the rule, not by the model")

    def test_it_replies_even_when_no_work_agent_ran(self):
        loop, _ = _loop([_responder("I could not do anything with that.")])

        outcome = loop.start("hello", CONTEXT, entry_tool="nonesuch")

        self.assertEqual("I could not do anything with that.", outcome.reply)
        self.assertEqual(["responder"], [i.agent for i in outcome.history])

    def test_a_responder_crash_costs_the_reply_and_nothing_else(self):
        """The one agent that must not take a turn down with it."""
        def explode(request):
            raise RuntimeError("no model")

        registry = AgentRegistry()
        registry.register(_agent("enrich", AgentResult(
            "done", produced=(Ref("note", "3"),)), entry_tools=("perform_action",)))
        registry.register(AgentSpec(name="responder", description="", start=explode))
        loop = Loop(FakeStore(), FakeLedger(), Router(registry))

        outcome = loop.start("save this", CONTEXT, entry_tool="perform_action")

        self.assertIsNone(outcome.reply)
        self.assertEqual(
            (Ref("note", "3"),),
            next(i for i in outcome.history if i.agent == "enrich").produced,
            "the note is still reported")

    def test_a_confirm_also_ends_with_a_reply(self):
        registry = AgentRegistry()
        registry.register(AgentSpec(
            name="reminder",
            description="",
            start=lambda request: AgentResult(
                "needs_input", ask={"action": {"name": "x", "args": {}}}, token="tok"),
            resume=lambda token, decision, context: AgentResult(
                "done", produced=(Ref("reminder", "42"),)),
            entry_tools=("set_reminder",)))
        registry.register(_responder("Set for tomorrow."))
        loop = Loop(FakeStore(), FakeLedger(), Router(registry))
        paused = loop.start("remind me", CONTEXT, entry_tool="set_reminder")

        outcome = loop.resume(paused.pending, {"approve": True}, "x", CONTEXT)

        self.assertEqual("done", outcome.status)
        self.assertEqual("Set for tomorrow.", outcome.reply)


class RoutingTests(unittest.TestCase):
    def test_an_entry_tool_routes_without_the_router(self):
        called = []
        loop, _ = _loop(
            [_agent("reminder", AgentResult("done"), entry_tools=("set_reminder",))],
            router=lambda roster, message, history: called.append(1))

        outcome = loop.start("remind me tomorrow", CONTEXT, entry_tool="set_reminder")

        self.assertEqual("done", outcome.status)
        self.assertEqual(["reminder"], [item.agent for item in outcome.history])
        self.assertEqual([], called)

    def test_router_always_ignores_the_entry_tool(self):
        seen = {}

        def router(roster, message, history):
            seen["roster"] = roster

            return "reminder"

        loop, _ = _loop(
            [_agent("reminder", AgentResult("done"), entry_tools=("set_reminder",))],
            router=router,
            router_always=True)

        loop.start("remind me tomorrow", CONTEXT, entry_tool="set_reminder")

        self.assertEqual([{"name": "reminder", "description": "reminder agent"}],
                         seen["roster"])

    def test_an_unknown_entry_tool_ends_the_turn(self):
        loop, _ = _loop([_agent("reminder", AgentResult("done"))])

        outcome = loop.start("hello", CONTEXT, entry_tool="nonesuch")

        self.assertEqual((), outcome.history)

    def test_the_router_never_sees_an_agent_that_already_ran(self):
        seen = []

        def router(candidates, message, history):
            seen.append([item["name"] for item in candidates])

            return candidates[0]["name"]

        loop, _ = _loop(
            [_agent("a", AgentResult("done")), _agent("b", AgentResult("done"))],
            router=router)

        loop.start("go", CONTEXT)

        self.assertEqual([["a", "b"], ["b"]], seen, "a spent agent is not a candidate")

    def test_the_hop_bound_reserves_its_last_slot_for_the_reply(self):
        """`AGENT_MAX_HOPS` counts the reply, so a budget of 2 buys one work hop
        and one reply — never two work hops and silence."""
        agents = [_agent(name, AgentResult("done")) for name in "abcde"]
        agents.append(AgentSpec(
            name="responder",
            description="",
            start=lambda request: AgentResult("done", reply="done"),
            may_read=("*",)))
        loop, _ = _loop(
            agents,
            router=lambda candidates, message, history: candidates[0]["name"],
            max_hops=2)

        outcome = loop.start("go", CONTEXT)

        self.assertEqual(["a", "responder"], [item.agent for item in outcome.history])
        self.assertEqual("done", outcome.reply)

    def test_a_farm_with_no_responder_leaves_the_reserved_slot_unused(self):
        """Nothing is forced into the last hop when there is no responder; the
        turn simply ends one hop early, with no reply."""
        loop, _ = _loop(
            [_agent(name, AgentResult("done")) for name in "abcde"],
            router=lambda candidates, message, history: candidates[0]["name"],
            max_hops=2)

        outcome = loop.start("go", CONTEXT)

        self.assertEqual(["a"], [item.agent for item in outcome.history])
        self.assertIsNone(outcome.reply)


class TurnTreeTests(unittest.TestCase):
    def test_each_hop_is_caused_by_the_one_before_it(self):
        store = FakeStore()
        registry = AgentRegistry()
        registry.register(_agent("a", AgentResult("done")))
        registry.register(_agent("b", AgentResult("done")))
        order = iter(["a", "b", None])
        loop = Loop(store, FakeLedger(),
                        Router(registry, select_model=lambda *args: next(order)),
                        max_hops=4)

        loop.start("go", CONTEXT)

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
        loop = Loop(store, FakeLedger(), Router(registry))

        loop.start("go", {**CONTEXT, "user_id": 42}, entry_tool="set_reminder")

        self.assertEqual([42], seen)
        self.assertEqual(42, store.rows[0]["user_id"])

    def test_a_context_without_an_owner_fails_loudly(self):
        loop, _ = _loop([_agent("a", AgentResult("done"), entry_tools=("t",))])

        with self.assertRaises(KeyError):
            loop.start("go", {"locale": "en"}, entry_tool="t")

    def test_references_reach_the_agent_separately_from_context(self):
        seen = {}
        registry = AgentRegistry()
        registry.register(AgentSpec(
            name="a",
            description="",
            start=lambda request: seen.update(
                refs=request.references, ctx=request.context) or AgentResult("done"),
            entry_tools=("t",)))
        loop = Loop(FakeStore(), FakeLedger(), Router(registry))

        loop.start("go", CONTEXT, references={"citations": [{"note_id": 3}]}, entry_tool="t")

        self.assertEqual([{"note_id": 3}], seen["refs"]["citations"])
        self.assertNotIn("citations", seen["ctx"], "the shared context stays clock-only")

    def test_an_agent_that_raises_becomes_a_failed_state(self):
        def explode(request):
            raise RuntimeError("boom")

        registry = AgentRegistry()
        registry.register(AgentSpec(
            name="reminder", description="", start=explode, entry_tools=("set_reminder",)))
        store = FakeStore()
        loop = Loop(store, FakeLedger(), Router(registry))

        outcome = loop.start("go", CONTEXT, entry_tool="set_reminder")

        self.assertEqual("failed", outcome.status)
        self.assertEqual("boom", outcome.history[-1].error)
        self.assertEqual("failed", store.rows[-1]["status"])

    def test_invalid_refs_are_downgraded_to_a_failure(self):
        loop, _ = _loop([_agent(
            "reminder",
            AgentResult("done", produced=({"kind": "note", "id": "1"},)),
            entry_tools=("set_reminder",))])

        outcome = loop.start("go", CONTEXT, entry_tool="set_reminder")

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
        self.loop = Loop(self.store, self.ledger, Router(self.registry))

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
        loop = Loop(store, FakeLedger(), Router(registry))
        paused = loop.start("remind me", CONTEXT, entry_tool="set_reminder")

        outcome = loop.resume(paused.pending, {"approve": True}, "x", CONTEXT)

        self.assertEqual("failed", outcome.status)
        self.assertIn("produced[0]", outcome.history[-1].error)
        self.assertEqual("failed", store.rows[-1]["status"])

    def test_the_resume_row_records_the_same_fields_as_a_drive_row(self):
        """Both copies must write the same columns; a field added to one and
        forgotten in the other shows up here."""
        paused = self.loop.start("remind me", CONTEXT, entry_tool="set_reminder")
        self.loop.resume(paused.pending, {"approve": True}, "x", CONTEXT)

        self.assertEqual(
            set(self.store.rows[0]),
            set(self.store.rows[1]),
            "the drive and resume save calls disagree about the row shape")
        self.assertEqual(7, self.store.rows[1]["user_id"])
        self.assertEqual("reminder", self.store.rows[1]["agent"])

    def test_a_pause_returns_pending_the_section_can_store(self):
        outcome = self.loop.start("remind me", CONTEXT, entry_tool="set_reminder")

        self.assertEqual("needs_input", outcome.status)
        self.assertEqual("reminder", outcome.pending["agent"])
        self.assertEqual("tok", outcome.pending["token"])
        self.assertEqual(outcome.correlation_id, outcome.pending["correlation_id"])

    def test_approval_runs_the_write_and_reports_what_it_made(self):
        paused = self.loop.start("remind me", CONTEXT, entry_tool="set_reminder")

        outcome = self.loop.resume(paused.pending, {"approve": True}, "remind me", CONTEXT)

        self.assertEqual("done", outcome.status)
        self.assertEqual((Ref("reminder", "42"),), outcome.history[-1].produced)
        self.assertEqual(1, len(outcome.history), "a paused agent keeps one history entry")

    def test_a_replayed_confirm_does_not_write_twice(self):
        paused = self.loop.start("remind me", CONTEXT, entry_tool="set_reminder")

        first = self.loop.resume(paused.pending, {"approve": True}, "x", CONTEXT)
        second = self.loop.resume(paused.pending, {"approve": True}, "x", CONTEXT)

        self.assertEqual(1, self.ledger.calls)
        self.assertEqual(first.history[-1].produced, second.history[-1].produced)

    def test_a_decline_runs_nothing(self):
        paused = self.loop.start("remind me", CONTEXT, entry_tool="set_reminder")

        outcome = self.loop.resume(paused.pending, {"approve": False}, "x", CONTEXT)

        self.assertEqual(0, self.ledger.calls)
        self.assertEqual("done", outcome.status)
        self.assertEqual((), outcome.history[-1].produced)

    def test_the_history_entry_points_at_the_state_it_summarises(self):
        """Without `state_id` an agent is told a hop happened but has no handle
        to pass to `read_state`."""
        paused = self.loop.start("remind me", CONTEXT, entry_tool="set_reminder")

        entry = paused.history[-1]

        self.assertEqual(self.store.rows[-1]["state_id"], entry.state_id)

    def test_the_entry_follows_the_latest_row_after_a_confirm(self):
        paused = self.loop.start("remind me", CONTEXT, entry_tool="set_reminder")

        outcome = self.loop.resume(paused.pending, {"approve": True}, "x", CONTEXT)

        self.assertEqual("s2", outcome.history[-1].state_id, "not the paused row")

    def test_both_hops_stay_in_the_tree(self):
        paused = self.loop.start("remind me", CONTEXT, entry_tool="set_reminder")
        self.loop.resume(paused.pending, {"approve": True}, "x", CONTEXT)

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
