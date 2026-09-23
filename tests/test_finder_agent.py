"""The finder agent's side of the broker contract.

The graph, the tool registry and the model gateway are stubbed, so this
exercises the adapter — the clock, the messages it assembles, the state it hands
back and the refs it reports — without LangGraph, a model, or a database. The
nodes' own logic is covered separately below, against the real modules.
"""

import sys
import types
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo


def _stub_if_absent(name: str, **attributes) -> None:
    """Install a stand-in only where the real module cannot be imported.

    LangGraph and psycopg are installed in CI and on a developer machine but not
    in every sandbox. Replacing them unconditionally would shadow the real ones
    for every test module imported after this one, so absence is the condition.
    """
    try:
        __import__(name)

        return
    except Exception:
        pass

    module = types.ModuleType(name)

    for attribute, value in attributes.items():
        setattr(module, attribute, value)

    sys.modules[name] = module


def _install_stubs():
    """Stand in for the modules `agents.finder.agent` imports at module level."""
    run = {"state": None, "invoked": []}

    _stub_if_absent("langgraph.types", Command=object)
    _stub_if_absent("langgraph.graph", END="__end__")
    _stub_if_absent(
        "agents.runtime.checkpoint",
        graph_config=lambda namespace, thread_id, max_steps: {
            "configurable": {"thread_id": f"{namespace}:{thread_id}"},
        })

    # The graph is stubbed whole and unconditionally: this file tests the
    # adapter around it — what it starts the graph with, and what it makes of
    # the state that comes back — never LangGraph's own traversal.
    graph = types.ModuleType("agents.finder.graph")
    graph.FINDER_GRAPH = "finder-graph"
    sys.modules["agents.finder.graph"] = graph

    # The tool package reaches psycopg at import time; the nodes only need the
    # registry and the read specs it exposes. `ActNodeTests` rebinds `TOOLS`
    # either way, so a real package here is fine.
    _stub_if_absent("tools.finder", TOOLS={}, READ_TOOL_SPECS=[])

    return run


def _install_gateway():
    """Stand in for the model gateway, which reaches `openai` at import time.

    Idempotent and shared: more than one test module stubs this, and the last
    one to install must not orphan the handle an earlier one already gave to an
    agent module it imported.
    """
    existing = sys.modules.get("agents.runtime.model_gateway")

    if existing is not None and hasattr(existing, "GATEWAY"):
        return existing.GATEWAY

    gateway = {"response": None, "error": None, "requests": []}

    module = types.ModuleType("agents.runtime.model_gateway")

    def chat_completion(**model_request):
        gateway["requests"].append(model_request)

        if gateway["error"] is not None:
            raise gateway["error"]

        return gateway["response"]

    module.chat_completion = chat_completion
    module.ModelGatewayError = RuntimeError
    module.GATEWAY = gateway
    sys.modules["agents.runtime.model_gateway"] = module

    return gateway


RUN = _install_stubs()
GATEWAY = _install_gateway()

import config  # noqa: E402
from agents.contracts import AgentRequest, Ref, ToolResult  # noqa: E402
from agents.finder import agent  # noqa: E402
from agents.runtime import loop  # noqa: E402

CONTEXT = {
    "user_id": 7,
    "now": "2026-09-23T09:00:00",
    "tz": "Europe/Kyiv",
    "locale": "uk",
}


def _tool_call(call_id, name, arguments):
    """The shape the OpenAI SDK returns for one tool call."""
    function = types.SimpleNamespace(name=name, arguments=arguments)

    return types.SimpleNamespace(id=call_id, function=function)


def _completion(content=None, tool_calls=None):
    """The shape the OpenAI SDK returns, as far as the reason node reads it."""
    message = types.SimpleNamespace(content=content, tool_calls=tool_calls or [])

    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


def _request(message="what did I write about Postgres?", **references):
    return AgentRequest(
        request_id="r1",
        correlation_id="c1",
        causation_id=None,
        agent="finder",
        message=message,
        context=CONTEXT,
        references=dict(references),
        hops_left=4)


class AdapterTests(unittest.TestCase):
    """`start` is the whole contract: one graph run in, one `AgentResult` out."""

    def setUp(self):
        RUN["invoked"].clear()
        self._invoke = loop.invoke
        loop.invoke = self._record_run

    def tearDown(self):
        loop.invoke = self._invoke

    def _record_run(self, graph, graph_config, state):
        RUN["invoked"].append({
            "graph": graph,
            "graph_config": graph_config,
            "state": state,
        })

        return RUN["state"] or {}

    def test_the_answer_travels_in_state_not_as_a_reply(self):
        """The responder is the only agent that speaks to the user; finder's
        answer reaches it through `read_state`."""
        RUN["state"] = {"reply": "You wrote about tuning.", "citations": [], "trace": {}}

        result = agent.start(_request())

        self.assertEqual("done", result.status)
        self.assertIsNone(result.reply)
        self.assertEqual("You wrote about tuning.", result.state["answer"])

    def test_every_cited_note_is_reported_as_a_ref(self):
        RUN["state"] = {
            "reply": "Two of them.",
            "citations": [{"note_id": 12, "title": "a"}, {"note_id": 5, "title": "b"}],
            "trace": {},
        }

        result = agent.start(_request())

        self.assertEqual((Ref("note", "12"), Ref("note", "5")), result.produced)
        self.assertEqual(2, len(result.state["citations"]), "the chips travel too")

    def test_a_citation_without_an_id_is_dropped_not_fatal(self):
        """`find_problems` in the broker downgrades a malformed ref to a failed
        hop, so a half-formed citation must never become one."""
        RUN["state"] = {"reply": "x", "citations": [{"title": "no id"}], "trace": {}}

        result = agent.start(_request())

        self.assertEqual((), result.produced)

    def test_an_empty_answer_is_still_a_finished_hop(self):
        """Nothing found is an answer. Failing here would send the turn to the
        responder as an error when the honest reply is "I could not find it"."""
        RUN["state"] = {}

        result = agent.start(_request())

        self.assertEqual("done", result.status)
        self.assertEqual("", result.state["answer"])

    def test_it_never_pauses_so_it_reports_no_ask_or_token(self):
        RUN["state"] = {"reply": "x", "citations": [], "trace": {}}

        result = agent.start(_request())

        self.assertIsNone(result.ask)
        self.assertIsNone(result.token)


class MessageTests(unittest.TestCase):
    """What the graph is started with: the thread so far plus this turn."""

    def setUp(self):
        RUN["state"] = {"reply": "x", "citations": [], "trace": {}}
        RUN["invoked"].clear()
        self._invoke = loop.invoke
        loop.invoke = lambda graph, graph_config, state: (
            RUN["invoked"].append(state) or RUN["state"])

    def tearDown(self):
        loop.invoke = self._invoke

    def _messages(self, request):
        agent.start(request)

        return RUN["invoked"][0]["messages"]

    def test_the_turns_message_is_appended_as_the_user_turn(self):
        messages = self._messages(_request("where are my notes on tuning?"))

        self.assertEqual(
            {"role": "user", "content": "where are my notes on tuning?"},
            messages[-1])

    def test_prior_turns_arrive_as_a_reference_not_as_broker_state(self):
        """The thread belongs to the calling section; the farm knows nothing
        about it, so it travels in `references`."""
        messages = self._messages(_request(
            messages=[{"role": "user", "content": "earlier"},
                      {"role": "assistant", "content": "answered"}]))

        self.assertIn({"role": "user", "content": "earlier"}, messages)
        self.assertIn({"role": "assistant", "content": "answered"}, messages)

    def test_the_system_prompt_leads_and_carries_the_clock(self):
        messages = self._messages(_request())

        self.assertEqual("system", messages[0]["role"])
        self.assertIn("2026-09-23T09:00:00", messages[0]["content"])
        self.assertIn("Europe/Kyiv", messages[0]["content"])

    def test_no_thread_history_still_produces_a_valid_run(self):
        messages = self._messages(_request())

        self.assertEqual(2, len(messages), "just the system prompt and the message")

    def test_the_owner_and_locale_reach_the_graph_context(self):
        agent.start(_request())

        context = RUN["invoked"][0]["context"]
        self.assertEqual(7, context["user_id"])
        self.assertEqual("uk", context["locale"])


class ClockTests(unittest.TestCase):
    def test_a_named_zone_is_restored_as_a_zone(self):
        _, tz, _ = agent._restore_clock({"now": "2026-09-23T09:00:00", "tz": "Europe/Kyiv"})

        self.assertEqual(ZoneInfo("Europe/Kyiv"), tz)

    def test_a_missing_timezone_stays_none(self):
        now, tz, locale = agent._restore_clock({"now": "2026-09-23T09:00:00", "tz": None})

        self.assertEqual(datetime(2026, 9, 23, 9, 0), now)
        self.assertIsNone(tz)
        self.assertEqual("en", locale)

    def test_a_datetime_passes_through_unparsed(self):
        moment = datetime(2026, 9, 23, 9, 0)
        now, _, _ = agent._restore_clock({"now": moment, "tz": None})

        self.assertIs(moment, now)


class PromptTests(unittest.TestCase):
    def test_it_is_not_told_to_hand_writes_to_a_named_agent(self):
        """The conversation controller's prompt named `perform_action` and
        `set_reminder`. A peer that names its peers is the coupling the farm
        exists to remove — and finder has no such tools to call."""
        from agents.finder.prompts import SYSTEM_PROMPT

        self.assertNotIn("perform_action", SYSTEM_PROMPT)
        self.assertNotIn("set_reminder", SYSTEM_PROMPT)

    def test_an_existing_system_message_is_replaced_not_stacked(self):
        from agents.finder.prompts import with_system

        messages = with_system([{"role": "system", "content": "stale"},
                                {"role": "user", "content": "hi"}])

        self.assertEqual(1, sum(1 for item in messages if item["role"] == "system"))
        self.assertNotIn("stale", messages[0]["content"])


class ReasonNodeTests(unittest.TestCase):
    """The one model step: call a read tool, or answer."""

    def setUp(self):
        GATEWAY["error"] = None
        GATEWAY["requests"].clear()

    def _run(self, state):
        from agents.finder.nodes import reason

        return reason.run(state)

    def test_a_tool_call_is_extracted_and_the_turn_keeps_going(self):
        GATEWAY["response"] = _completion(tool_calls=[
            _tool_call("c1", "search_notes", '{"query": "tuning"}')])

        state_update = self._run({"messages": [], "steps": 0})

        self.assertEqual("search_notes", state_update["tool_call"]["name"])
        self.assertEqual({"query": "tuning"}, state_update["tool_call"]["args"])
        self.assertNotIn("reply", state_update)

    def test_no_tool_call_means_the_content_is_the_answer(self):
        GATEWAY["response"] = _completion("You wrote about tuning.")

        state_update = self._run({"messages": [], "steps": 0})

        self.assertIsNone(state_update["tool_call"])
        self.assertEqual("You wrote about tuning.", state_update["reply"])

    def test_unparseable_arguments_become_empty_args_not_a_crash(self):
        GATEWAY["response"] = _completion(tool_calls=[
            _tool_call("c1", "get_note", "{not json")])

        state_update = self._run({"messages": [], "steps": 0})

        self.assertEqual({}, state_update["tool_call"]["args"])

    def test_the_last_step_is_offered_no_tools_so_it_must_answer(self):
        """Without this the loop could spend its budget and still return a tool
        call, and the hop would end with no answer at all."""
        GATEWAY["response"] = _completion("Here is what I found.")

        self._run({"messages": [], "steps": config.AGENT_MAX_STEPS})

        self.assertNotIn("tools", GATEWAY["requests"][0])

    def test_a_model_outage_answers_rather_than_failing_the_hop(self):
        outage = sys.modules["agents.runtime.model_gateway"].ModelGatewayError("down")
        outage.kind = "model_rate_limited"
        GATEWAY["error"] = outage

        state_update = self._run({"messages": [], "steps": 0})

        self.assertTrue(state_update["reply"])
        self.assertIsNone(state_update["tool_call"])
        self.assertEqual("model_rate_limited", state_update["trace"]["model_error"])


class ActNodeTests(unittest.TestCase):
    """One read tool, then back to reason. It never mutates anything."""

    def setUp(self):
        from tools import finder as tools

        self.calls = []
        self.registry = tools.TOOLS
        tools.TOOLS = {"search_notes": self._invoke, "get_note": self._invoke}
        self.result = ToolResult({"notes": []})

    def tearDown(self):
        from tools import finder as tools

        tools.TOOLS = self.registry

    def _invoke(self, context, args):
        self.calls.append({"context": context, "args": args})

        return self.result

    def _run(self, tool_call):
        from agents.finder.nodes import act

        return act.run({
            "messages": [],
            "context": {"user_id": 7, "now": "2026-09-23T09:00:00", "tz": "Europe/Kyiv"},
            "tool_call": tool_call,
        })

    def test_the_owner_scopes_every_read(self):
        self._run({"id": "c1", "name": "search_notes", "args": {"query": "x"}})

        self.assertEqual(7, self.calls[0]["context"]["user_id"])

    def test_citations_are_gathered_onto_the_turn(self):
        self.result = ToolResult(
            {"notes": []},
            citations=[{"note_id": 12, "title": "Tuning", "path": "Notes/x"}])

        state_update = self._run({"id": "c1", "name": "search_notes", "args": {}})

        self.assertEqual(12, state_update["citations"][0]["note_id"])
        self.assertEqual(12, state_update["reference_notes"][0]["note_id"])

    def test_the_result_returns_to_the_model_as_a_tool_message(self):
        state_update = self._run({"id": "c1", "name": "get_note", "args": {"note_id": 1}})

        message = state_update["messages"][-1]
        self.assertEqual("tool", message["role"])
        self.assertEqual("c1", message["tool_call_id"])

    def test_a_search_is_traced_as_rag_and_anything_else_as_a_tool(self):
        self.assertEqual(
            ["rag"],
            self._run({"id": "c1", "name": "search_notes", "args": {}})["trace"]["routes"])
        self.assertEqual(
            ["tool"],
            self._run({"id": "c2", "name": "get_note", "args": {}})["trace"]["routes"])


class RoutingTests(unittest.TestCase):
    def test_a_tool_call_goes_to_act(self):
        from agents.finder import routing

        self.assertEqual("act", routing.after_reason({"tool_call": {"name": "get_note"}}))

    def test_no_tool_call_ends_the_hop(self):
        from agents.finder import routing
        from langgraph.graph import END

        self.assertEqual(END, routing.after_reason({"tool_call": None}))


class SpecTests(unittest.TestCase):
    def test_it_claims_no_entry_tool_so_only_the_model_router_picks_it(self):
        self.assertEqual((), agent.SPEC.entry_tools)

    def test_it_never_pauses_so_it_needs_no_resume(self):
        self.assertIsNone(agent.SPEC.resume)

    def test_it_grants_itself_no_read_scope(self):
        """`may_read` gates the `read_state` tool, which finder does not call.
        An allowlist for a tool an agent never reaches is config nothing
        exercises — and it goes stale silently, as it did when it still named
        the deleted `conversation` agent."""
        self.assertEqual((), agent.SPEC.may_read)

    def test_the_description_tells_the_router_it_only_reads(self):
        self.assertIn("read", agent.SPEC.description.lower())


if __name__ == "__main__":
    unittest.main()
