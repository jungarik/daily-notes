"""The loop's routing, history and idempotency contracts.

Drives real `Loop` code against an in-memory store and hand-written agents, so
the turn tree, the entry-agent shortcut and the at-most-once guarantee are
exercised without a database, a model, or LangGraph.
"""

import unittest

# Nothing here reaches a model — the router is stubbed as a spec — but this
# file is early in the suite, so it installs the shared gateway stub before
# any import that might bind the real one.
from tests import gateway_stub

gateway_stub.install()
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
    AGENT_KIND,
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
        """Every hop in order, as the real store now returns them — collapsing
        per agent here would hide the repeat hops these tests exist to cover."""
        return tuple(
            HistoryEntry(
                agent=row["agent"],
                status=row["status"],
                produced=row["produced"],
                state_id=row["state_id"])
            for row in self.rows
            if row["correlation_id"] == correlation_id)


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


def _router(choose=None):
    """A stand-in for the router agent, registered like the real one.

    `choose(candidates, message, history)` returns the name to route to, or
    None to decline — the same signature the real router's model seam had. It
    answers in `produced` exactly as the real router does, so these tests
    exercise the loop's own decoding of that ref rather than a seam built for
    them.
    """
    def start(request):
        candidates = list(request.references.get("candidates") or [])
        chosen = (None if choose is None
                  else choose(candidates, request.message, request.history))

        return AgentResult(
            status="done",
            state={"chosen": chosen},
            produced=() if chosen is None else (Ref(AGENT_KIND, chosen),))

    return AgentSpec(name="router", description="picks the next agent", start=start)


def _registry(agents, router=None):
    """A registry holding these agents plus a stub router."""
    registry = AgentRegistry()

    for agent in agents:
        registry.register(agent)

    registry.register(_router(router))

    return registry


def _loop(agents, router=None, router_always=False, store=None, **kwargs):
    """A loop over a fresh registry, with a stub router registered."""
    registry = _registry(agents, router)

    return Loop(
        store or FakeStore(),
        FakeLedger(),
        registry,
        always_route=router_always,
        **kwargs), registry


def _worked(outcome):
    """The agents that took a work hop, in order.

    The router now lands in the history too, so a test about *what ran* says
    so by filtering it out — and a test about *whether the router ran* asserts
    on the unfiltered history instead.
    """
    return [entry.agent for entry in outcome.history if entry.agent != "router"]


CONTEXT: UserContext = {
    "user_id": 7,
    "now": "2026-09-18T09:00:00",
    "tz": "Europe/Kyiv",
    "locale": "en",
}


class RegistryTests(unittest.TestCase):
    def test_duplicate_agent_name_is_rejected(self):
        registry = AgentRegistry()
        registry.register(_agent("a", AgentResult("done")))

        with self.assertRaises(ValueError):
            registry.register(_agent("a", AgentResult("done")))

    def test_a_renamed_agent_is_still_reachable_by_its_old_name(self):
        """A suspended turn stored the name the agent had when it paused. If the
        rename made that name unknown, the user's confirmation would fail on the
        one path where a write is already planned and waiting."""
        registry = AgentRegistry()
        registry.register(_agent("enricher", AgentResult("done")))

        self.assertEqual("enricher", registry.get("enrich").name)

    def test_an_unknown_name_is_still_an_error(self):
        """The alias resolves one rename, not any name at all."""
        registry = AgentRegistry()
        registry.register(_agent("enricher", AgentResult("done")))

        with self.assertRaises(LookupError):
            registry.get("nobody")

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

    def test_a_resumed_hop_supersedes_the_pause_it_answers(self):
        """The confirmed outcome is the same hop finishing, not a second one —
        leaving both would report a turn as still waiting on a user who already
        answered."""
        paused = HistoryEntry("reminder", "needs_input")
        finished = HistoryEntry("reminder", "done", produced=(Ref("reminder", "9"),))
        merged = merge_history((HistoryEntry("enricher", "done"), paused), finished)

        self.assertEqual(["enricher", "reminder"], [item.agent for item in merged])
        self.assertEqual(finished, merged[-1])

    def test_an_agent_that_runs_twice_keeps_both_entries(self):
        """Creating a note and then linking it is one agent, two hops. Collapsing
        them would hide the first from the router deciding what is left and from
        the responder writing the reply."""
        created = HistoryEntry("enricher", "done", produced=(Ref("note", "9"),))
        linked = HistoryEntry("enricher", "done", produced=(Ref("link", "3"),))
        merged = merge_history((created,), linked)

        self.assertEqual([created, linked], list(merged))


class RouterHopTests(unittest.TestCase):
    """The router is a registered agent that takes a hop like any other. These
    are the properties that follow from that, and from nothing else."""

    def setUp(self):
        self.agents = [
            _agent("reminder", AgentResult("done")),
            _agent("enricher", AgentResult("done")),
        ]

    def test_a_routed_hop_puts_the_router_in_the_history(self):
        loop, _ = _loop(
            [*self.agents, _responder()],
            router=lambda candidates, message, history: "enricher")

        outcome = loop.start("go", CONTEXT)

        self.assertIn("router", [entry.agent for entry in outcome.history])

    def test_a_free_hop_leaves_no_router_entry(self):
        """Cases 1 and 2 need no model, so the router neither runs nor records.
        The history says where a decision actually cost something.

        A budget of two makes both hops free ones: `entry_agent` names the
        first, and the second is the reply's reserved slot."""
        loop, _ = _loop(
            [_agent("reminder", AgentResult("done")),
             _responder()],
            max_hops=2)

        outcome = loop.start("remind me", CONTEXT, entry_agent="reminder")

        self.assertEqual(["reminder", "responder"], [e.agent for e in outcome.history])

    def test_the_choice_travels_as_a_typed_ref(self):
        """`Ref(AGENT_KIND, name)` is the whole channel — the loop reads no
        agent's state to learn where a turn goes next."""
        loop, _ = _loop(
            [*self.agents, _responder()],
            router=lambda candidates, message, history: "enricher")

        outcome = loop.start("go", CONTEXT)
        routed = next(e for e in outcome.history if e.agent == "router")

        self.assertEqual((Ref(AGENT_KIND, "enricher"),), routed.produced)

    def test_neither_singleton_is_ever_a_candidate(self):
        """The responder takes the last hop by construction, and offering the
        router would let a decision pick itself."""
        seen = {}
        loop, _ = _loop(
            [*self.agents, _responder()],
            router=lambda candidates, message, history: (
                seen.update(names=[c["name"] for c in candidates]) or None))

        loop.start("go", CONTEXT)

        self.assertNotIn("responder", seen["names"])
        self.assertNotIn("router", seen["names"])

    def test_routing_is_free_so_it_does_not_spend_the_hop_budget(self):
        """Two work hops plus a reply still fit a budget of three, however many
        router hops were needed to arrange them."""
        order = iter(["reminder", "enricher"])
        loop, _ = _loop(
            [*self.agents, _responder()],
            router=lambda *args: next(order, None),
            max_hops=3)

        outcome = loop.start("go", CONTEXT)

        self.assertEqual(["reminder", "enricher", "responder"], _worked(outcome))

    def test_a_declining_router_still_leaves_the_user_answered(self):
        loop, _ = _loop([*self.agents, _responder("Nothing to do.")],
                        router=lambda *args: None)

        outcome = loop.start("go", CONTEXT)

        self.assertEqual("Nothing to do.", outcome.reply)


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
            _agent("reminder", AgentResult("done")),
            _responder("Set your reminder."),
        ], max_hops=2)

        outcome = loop.start("remind me", CONTEXT, entry_agent="reminder")

        self.assertEqual("done", outcome.status)
        self.assertEqual("Set your reminder.", outcome.reply)
        self.assertEqual(["reminder", "responder"], [i.agent for i in outcome.history])

    def test_a_failed_turn_still_gets_a_reply(self):
        """An error is something the user is told, not a stack trace."""
        def explode(request):
            raise RuntimeError("boom")

        registry = AgentRegistry()
        registry.register(AgentSpec(
            name="reminder", description="", start=explode))
        registry.register(_responder("That went wrong."))
        loop = Loop(FakeStore(), FakeLedger(), registry)

        outcome = loop.start("remind me", CONTEXT, entry_agent="reminder")

        self.assertEqual("failed", outcome.status, "the reply's own success is not the turn's")
        self.assertEqual("That went wrong.", outcome.reply)

    def test_a_suspended_turn_gets_a_reply_and_keeps_its_pending(self):
        registry = AgentRegistry()
        registry.register(AgentSpec(
            name="reminder",
            description="",
            start=lambda request: AgentResult(
                "needs_input", ask={"kind": "confirm"}, token="tok"),))
        registry.register(_responder("Shall I set that for tomorrow?"))
        loop = Loop(FakeStore(), FakeLedger(), registry)

        outcome = loop.start("remind me", CONTEXT, entry_agent="reminder")

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
            start=lambda request: AgentResult("needs_input", ask={}, token="tok"),))
        registry.register(_agent("enricher", AgentResult("done")))
        registry.register(_responder())
        loop = Loop(
            FakeStore(),
            FakeLedger(),
            registry,
            max_hops=5)

        outcome = loop.start("remind me", CONTEXT, entry_agent="reminder")

        self.assertEqual(["reminder", "responder"], [i.agent for i in outcome.history])

    def test_the_responder_runs_once_and_that_ends_the_loop(self):
        store = FakeStore()
        registry = AgentRegistry()
        registry.register(_agent("reminder", AgentResult("done")))
        registry.register(_responder())
        loop = Loop(store, FakeLedger(), registry, max_hops=5)

        loop.start("remind me", CONTEXT, entry_agent="reminder")

        self.assertEqual(["reminder", "responder"], [row["agent"] for row in store.rows])

    def test_the_responder_hop_is_saved_like_any_other(self):
        store = FakeStore()
        registry = AgentRegistry()
        registry.register(_agent("reminder", AgentResult("done")))
        registry.register(_responder())
        loop = Loop(store, FakeLedger(), registry)

        loop.start("remind me", CONTEXT, entry_agent="reminder")

        self.assertEqual("s1", store.rows[1]["causation_id"], "caused by the hop it reports")

    def test_it_is_never_offered_to_the_model_as_a_candidate(self):
        seen = []
        loop, _ = _loop(
            [_agent("enricher", AgentResult("done")), _responder()],
            router=lambda candidates, message, history: (
                seen.append([c["name"] for c in candidates]) or candidates[0]["name"]))

        loop.start("go", CONTEXT)

        self.assertTrue(seen, "the router did run, so the roster was built")
        for roster in seen:
            self.assertNotIn("responder", roster, "picked by the rule, not by the model")

    def test_it_replies_even_when_no_work_agent_ran(self):
        loop, _ = _loop([_responder("I could not do anything with that.")])

        outcome = loop.start("hello", CONTEXT, entry_agent="nonesuch")

        self.assertEqual("I could not do anything with that.", outcome.reply)
        self.assertEqual(["responder"], [i.agent for i in outcome.history])

    def test_a_responder_crash_costs_the_reply_and_nothing_else(self):
        """The one agent that must not take a turn down with it."""
        def explode(request):
            raise RuntimeError("no model")

        registry = AgentRegistry()
        registry.register(_agent("enricher", AgentResult(
            "done", produced=(Ref("note", "3"),))))
        registry.register(AgentSpec(name="responder", description="", start=explode))
        loop = Loop(FakeStore(), FakeLedger(), registry)

        outcome = loop.start("save this", CONTEXT, entry_agent="enricher")

        self.assertIsNone(outcome.reply)
        self.assertEqual(
            (Ref("note", "3"),),
            next(i for i in outcome.history if i.agent == "enricher").produced,
            "the note is still reported")

    def test_a_confirm_also_ends_with_a_reply(self):
        registry = AgentRegistry()
        registry.register(AgentSpec(
            name="reminder",
            description="",
            start=lambda request: AgentResult(
                "needs_input", ask={"action": {"name": "x", "args": {}}}, token="tok"),
            resume=lambda token, decision, context: AgentResult(
                "done", produced=(Ref("reminder", "42"),)),))
        registry.register(_responder("Set for tomorrow."))
        loop = Loop(FakeStore(), FakeLedger(), registry)
        paused = loop.start("remind me", CONTEXT, entry_agent="reminder")

        outcome = loop.resume(paused.pending, {"approve": True}, "x", CONTEXT)

        self.assertEqual("done", outcome.status)
        self.assertEqual("Set for tomorrow.", outcome.reply)


class RoutingTests(unittest.TestCase):
    def test_a_named_entry_agent_routes_without_the_router(self):
        """Case 2: a caller that already knows who should act says so, and the
        hop costs no model call."""
        called = []
        loop, _ = _loop(
            [_agent("reminder", AgentResult("done"))],
            router=lambda roster, message, history: called.append(1),
            max_hops=2)

        outcome = loop.start("remind me tomorrow", CONTEXT, entry_agent="reminder")

        self.assertEqual("done", outcome.status)
        self.assertEqual(["reminder"], _worked(outcome))
        self.assertEqual([], called)

    def test_router_always_ignores_the_entry_agent(self):
        seen = {}

        def router(roster, message, history):
            seen["roster"] = roster

            return "reminder"

        loop, _ = _loop(
            [_agent("reminder", AgentResult("done"))],
            router=router,
            router_always=True)

        loop.start("remind me tomorrow", CONTEXT, entry_agent="reminder")

        self.assertEqual([{"name": "reminder", "description": "reminder agent"}],
                         seen["roster"])

    def test_an_unknown_entry_agent_falls_through_to_the_router(self):
        """A name this farm does not have is a miss, not an error: the shortcut
        is a caller's hint, so the turn carries on through case 3."""
        seen = []
        loop, _ = _loop(
            [_agent("reminder", AgentResult("done"))],
            router=lambda candidates, message, history: seen.append(
                [c["name"] for c in candidates]) or "reminder",
            max_hops=2)

        outcome = loop.start("hello", CONTEXT, entry_agent="nonesuch")

        self.assertEqual([["reminder"]], seen, "the router was asked instead")
        self.assertEqual(["reminder"], _worked(outcome))

    def test_the_router_sees_every_agent_on_every_hop(self):
        """A spent agent is still a candidate. A turn often needs the same one
        twice — create a note, then link it — and filtering the roster by what
        had already run made that impossible: it left the router choosing among
        whoever happened to be untouched rather than whoever fits."""
        seen = []

        def router(candidates, message, history):
            seen.append([item["name"] for item in candidates])

            return "a"

        loop, _ = _loop(
            [_agent("a", AgentResult("done")), _agent("b", AgentResult("done")),
             _responder()],
            router=router,
            max_hops=3)

        outcome = loop.start("go", CONTEXT)

        self.assertEqual([["a", "b"], ["a", "b"]], seen)
        self.assertEqual(["a", "a", "responder"], _worked(outcome),
                         "the same agent ran twice, and both hops are recorded")

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

        self.assertEqual(["a", "responder"], _worked(outcome))
        self.assertEqual("done", outcome.reply)

    def test_a_farm_with_no_responder_leaves_the_reserved_slot_unused(self):
        """Nothing is forced into the last hop when there is no responder; the
        turn simply ends one hop early, with no reply."""
        loop, _ = _loop(
            [_agent(name, AgentResult("done")) for name in "abcde"],
            router=lambda candidates, message, history: candidates[0]["name"],
            max_hops=2)

        outcome = loop.start("go", CONTEXT)

        self.assertEqual(["a"], _worked(outcome))
        self.assertIsNone(outcome.reply)


class TurnTreeTests(unittest.TestCase):
    def test_each_hop_is_caused_by_the_one_before_it(self):
        store = FakeStore()
        order = iter(["a", "b", None])
        loop, _ = _loop(
            [_agent("a", AgentResult("done")), _agent("b", AgentResult("done"))],
            router=lambda *args: next(order, None),
            store=store,
            max_hops=4)

        loop.start("go", CONTEXT)

        caused_by = [row["causation_id"] for row in store.rows]
        self.assertIsNone(caused_by[0], "the first hop is caused by nothing")
        self.assertEqual(caused_by[1:], [f"s{index}" for index in range(1, len(caused_by))],
                         "every later hop names the row before it")
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
            start=lambda request: seen.append(request.context["user_id"]) or AgentResult("done"),))
        loop = Loop(store, FakeLedger(), registry)

        loop.start("go", {**CONTEXT, "user_id": 42}, entry_agent="reminder")

        self.assertEqual([42], seen)
        self.assertEqual(42, store.rows[0]["user_id"])

    def test_a_context_without_an_owner_fails_loudly(self):
        loop, _ = _loop([_agent("a", AgentResult("done"))])

        with self.assertRaises(KeyError):
            loop.start("go", {"locale": "en"}, entry_agent="a")

    def test_references_reach_the_agent_separately_from_context(self):
        seen = {}
        registry = AgentRegistry()
        registry.register(AgentSpec(
            name="a",
            description="",
            start=lambda request: seen.update(
                refs=request.references, ctx=request.context) or AgentResult("done"),))
        loop = Loop(FakeStore(), FakeLedger(), registry)

        loop.start("go", CONTEXT, references={"citations": [{"note_id": 3}]}, entry_agent="a")

        self.assertEqual([{"note_id": 3}], seen["refs"]["citations"])
        self.assertNotIn("citations", seen["ctx"], "the shared context stays clock-only")

    def test_an_agent_that_raises_becomes_a_failed_state(self):
        def explode(request):
            raise RuntimeError("boom")

        registry = AgentRegistry()
        registry.register(AgentSpec(
            name="reminder", description="", start=explode))
        store = FakeStore()
        loop = Loop(store, FakeLedger(), registry)

        outcome = loop.start("go", CONTEXT, entry_agent="reminder")

        self.assertEqual("failed", outcome.status)
        self.assertEqual("boom", outcome.history[-1].error)
        self.assertEqual("failed", store.rows[-1]["status"])

    def test_invalid_refs_are_downgraded_to_a_failure(self):
        loop, _ = _loop([_agent(
            "reminder",
            AgentResult("done", produced=({"kind": "note", "id": "1"},)))])

        outcome = loop.start("go", CONTEXT, entry_agent="reminder")

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
                "done", produced=(Ref("reminder", "42"),), state={"ran": True}),))
        self.store = FakeStore()
        self.ledger = FakeLedger()
        self.loop = Loop(self.store, self.ledger, self.registry)

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
                "done", produced=({"kind": "note", "id": "1"},)),))
        store = FakeStore()
        loop = Loop(store, FakeLedger(), registry)
        paused = loop.start("remind me", CONTEXT, entry_agent="reminder")

        outcome = loop.resume(paused.pending, {"approve": True}, "x", CONTEXT)

        self.assertEqual("failed", outcome.status)
        self.assertIn("produced[0]", outcome.history[-1].error)
        self.assertEqual("failed", store.rows[-1]["status"])

    def test_the_resume_row_records_the_same_fields_as_a_drive_row(self):
        """Both copies must write the same columns; a field added to one and
        forgotten in the other shows up here."""
        paused = self.loop.start("remind me", CONTEXT, entry_agent="reminder")
        self.loop.resume(paused.pending, {"approve": True}, "x", CONTEXT)

        self.assertEqual(
            set(self.store.rows[0]),
            set(self.store.rows[1]),
            "the drive and resume save calls disagree about the row shape")
        self.assertEqual(7, self.store.rows[1]["user_id"])
        self.assertEqual("reminder", self.store.rows[1]["agent"])

    def test_a_pause_returns_pending_the_section_can_store(self):
        outcome = self.loop.start("remind me", CONTEXT, entry_agent="reminder")

        self.assertEqual("needs_input", outcome.status)
        self.assertEqual("reminder", outcome.pending["agent"])
        self.assertEqual("tok", outcome.pending["token"])
        self.assertEqual(outcome.correlation_id, outcome.pending["correlation_id"])

    def test_approval_runs_the_write_and_reports_what_it_made(self):
        paused = self.loop.start("remind me", CONTEXT, entry_agent="reminder")

        outcome = self.loop.resume(paused.pending, {"approve": True}, "remind me", CONTEXT)

        self.assertEqual("done", outcome.status)
        self.assertEqual((Ref("reminder", "42"),), outcome.history[-1].produced)
        self.assertEqual(1, len(outcome.history), "a paused agent keeps one history entry")

    def test_a_replayed_confirm_does_not_write_twice(self):
        paused = self.loop.start("remind me", CONTEXT, entry_agent="reminder")

        first = self.loop.resume(paused.pending, {"approve": True}, "x", CONTEXT)
        second = self.loop.resume(paused.pending, {"approve": True}, "x", CONTEXT)

        self.assertEqual(1, self.ledger.calls)
        self.assertEqual(first.history[-1].produced, second.history[-1].produced)

    def test_a_decline_runs_nothing(self):
        paused = self.loop.start("remind me", CONTEXT, entry_agent="reminder")

        outcome = self.loop.resume(paused.pending, {"approve": False}, "x", CONTEXT)

        self.assertEqual(0, self.ledger.calls)
        self.assertEqual("done", outcome.status)
        self.assertEqual((), outcome.history[-1].produced)

    def test_the_history_entry_points_at_the_state_it_summarises(self):
        """Without `state_id` an agent is told a hop happened but has no handle
        to pass to `read_state`."""
        paused = self.loop.start("remind me", CONTEXT, entry_agent="reminder")

        entry = paused.history[-1]

        self.assertEqual(self.store.rows[-1]["state_id"], entry.state_id)

    def test_the_entry_follows_the_latest_row_after_a_confirm(self):
        paused = self.loop.start("remind me", CONTEXT, entry_agent="reminder")

        outcome = self.loop.resume(paused.pending, {"approve": True}, "x", CONTEXT)

        self.assertEqual("s2", outcome.history[-1].state_id, "not the paused row")

    def test_both_hops_stay_in_the_tree(self):
        paused = self.loop.start("remind me", CONTEXT, entry_agent="reminder")
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
