"""Case 3 of routing: the model that picks the next agent.

The gateway is stubbed, so this covers what the router agent promises the loop
— that it never raises, and never names an agent it was not offered — without an
API key or a network call.

The other two cases need no model and are driven through the loop in
`tests/test_loop.py`.
"""

import json
import types
import unittest

from tests import gateway_stub


GATEWAY = gateway_stub.install()

from agents.router import agent as routing  # noqa: E402
from agents.contracts import HistoryEntry, Ref  # noqa: E402

CANDIDATES = [
    {"name": "enricher", "description": "creates and edits notes"},
    {"name": "reminder", "description": "schedules reminders"},
]


def _completion(text):
    """The shape the OpenAI SDK returns, as far as the selector reads it."""
    message = types.SimpleNamespace(content=text)

    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


class ChooseNameTests(unittest.TestCase):
    """Pure parsing — every way a model can misbehave collapses to None."""

    def test_a_named_candidate_is_chosen(self):
        self.assertEqual(
            "enricher",
            routing.choose_name('{"agent": "enricher"}', CANDIDATES))

    def test_an_explicit_null_declines(self):
        self.assertIsNone(routing.choose_name('{"agent": null}', CANDIDATES))

    def test_an_agent_that_was_not_offered_is_refused(self):
        """A name outside the candidate list would route around "one agent, one
        entry" — and could name the responder, which is never a candidate."""
        self.assertIsNone(
            routing.choose_name('{"agent": "responder"}', CANDIDATES))
        self.assertIsNone(
            routing.choose_name('{"agent": "nonesuch"}', CANDIDATES))

    def test_prose_instead_of_json_declines(self):
        self.assertIsNone(
            routing.choose_name("I think enricher should go next!", CANDIDATES))

    def test_a_missing_key_declines(self):
        self.assertIsNone(routing.choose_name('{"choice": "enricher"}', CANDIDATES))

    def test_a_json_scalar_declines(self):
        """`json.loads("4")` parses fine and then has no `.get`."""
        self.assertIsNone(routing.choose_name("4", CANDIDATES))
        self.assertIsNone(routing.choose_name('"enricher"', CANDIDATES))

    def test_an_empty_answer_declines(self):
        self.assertIsNone(routing.choose_name("", CANDIDATES))


class PromptTests(unittest.TestCase):
    def setUp(self):
        GATEWAY["error"] = None
        GATEWAY["requests"].clear()
        GATEWAY["response"] = _completion('{"agent": "enricher"}')

    def test_the_prompt_lists_only_the_candidates_it_was_given(self):
        routing.select_agent_name(CANDIDATES, "save this", ())

        sent = GATEWAY["requests"][0]["messages"][1]["content"]
        self.assertIn("- enricher: creates and edits notes", sent)
        self.assertIn("- reminder: schedules reminders", sent)
        self.assertNotIn("responder", sent)

    def test_the_prompt_carries_the_record_not_agent_prose(self):
        history = (
            HistoryEntry("enricher", "done", produced=(Ref("note", "12"),)),
            HistoryEntry("reminder", "failed", error="no time found"),
        )

        routing.select_agent_name(CANDIDATES, "save this", history)

        sent = GATEWAY["requests"][0]["messages"][1]["content"]
        self.assertIn("enricher: done, produced note 12", sent)
        self.assertIn("reminder: failed", sent)
        self.assertIn("no time found", sent)

    def test_a_fresh_turn_says_so_rather_than_showing_an_empty_list(self):
        routing.select_agent_name(CANDIDATES, "save this", ())

        self.assertIn(
            "Nothing has run yet this turn.",
            GATEWAY["requests"][0]["messages"][1]["content"])

    def test_it_asks_for_json_at_zero_temperature(self):
        routing.select_agent_name(CANDIDATES, "save this", ())

        sent = GATEWAY["requests"][0]
        self.assertEqual({"type": "json_object"}, sent["response_format"])
        self.assertEqual(0, sent["temperature"])


class FailureTests(unittest.TestCase):
    """A router that cannot be reached must not take the turn with it — the
    responder still gets its hop, so the user is answered either way."""

    def setUp(self):
        GATEWAY["error"] = None
        GATEWAY["requests"].clear()

    def test_a_gateway_error_declines_rather_than_raising(self):
        GATEWAY["error"] = RuntimeError("model_rate_limited")

        self.assertIsNone(routing.select_agent_name(CANDIDATES, "go", ()))

    def test_a_malformed_response_object_declines(self):
        GATEWAY["response"] = types.SimpleNamespace(choices=[])

        self.assertIsNone(routing.select_agent_name(CANDIDATES, "go", ()))

    def test_a_none_content_declines(self):
        GATEWAY["response"] = _completion(None)

        self.assertIsNone(routing.select_agent_name(CANDIDATES, "go", ()))


class StartTests(unittest.TestCase):
    """The selector is the router's `select_model` seam and nothing more."""

    def setUp(self):
        GATEWAY["error"] = None
        GATEWAY["requests"].clear()

    def test_a_choice_is_reported_as_a_typed_ref(self):
        from agents.contracts import AGENT_KIND, AgentRequest, Ref

        GATEWAY["response"] = _completion('{"agent": "enricher"}')
        request = AgentRequest(
            request_id="r1",
            correlation_id="c1",
            causation_id=None,
            agent="router",
            message="save this",
            context={"user_id": 7},
            references={"candidates": CANDIDATES})

        result = routing.start(request)

        self.assertEqual((Ref(AGENT_KIND, "enricher"),), result.produced)
        self.assertEqual("done", result.status)


    def test_a_decline_produces_nothing(self):
        """An empty `produced` is how the router says "no one" — the loop reads
        that as the responder's cue, so a decline still ends in a reply."""
        from agents.contracts import AgentRequest

        GATEWAY["response"] = _completion('{"agent": null}')
        request = AgentRequest(
            request_id="r1", correlation_id="c1", causation_id=None,
            agent="router", message="go", context={"user_id": 7},
            references={"candidates": CANDIDATES})

        result = routing.start(request)

        self.assertEqual((), result.produced)
        self.assertEqual("done", result.status, "declining is not failing")

    def test_no_candidates_never_reaches_the_model(self):
        """The loop short-circuits this too, but the agent must not depend on
        that — asking a model to choose from nothing is pure cost."""
        from agents.contracts import AgentRequest

        GATEWAY["requests"].clear()
        request = AgentRequest(
            request_id="r1", correlation_id="c1", causation_id=None,
            agent="router", message="go", context={"user_id": 7},
            references={})

        result = routing.start(request)

        self.assertEqual((), result.produced)
        self.assertEqual([], GATEWAY["requests"])


class SpecTests(unittest.TestCase):
    def test_it_claims_no_entry_tool(self):
        """It is reached by name, never addressed by a tool — an entry tool
        would make it routable, and something has to choose first."""
        self.assertEqual((), routing.SPEC.entry_tools)

    def test_it_never_pauses_so_it_needs_no_resume(self):
        self.assertIsNone(routing.SPEC.resume)

    def test_it_grants_itself_no_read_scope(self):
        self.assertEqual((), routing.SPEC.may_read)

    def test_the_registry_knows_it_by_name(self):
        from agents.runtime.registry import ROUTER

        self.assertEqual(ROUTER, routing.SPEC.name)


if __name__ == "__main__":
    unittest.main()
