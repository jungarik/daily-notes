"""The responder: the one agent that writes to the user.

The model gateway is stubbed, so this covers what the responder promises the
farm — that it never fails, and that it reports the record rather than inventing
one — without an API key or a network call.
"""

import sys
import types
import unittest


def _install_stubs():
    """Stand in for the model gateway `agents.responder.agent` imports."""
    gateway = {"response": None, "error": None, "requests": []}

    module = types.ModuleType("agents.runtime.model_gateway")

    def chat_completion(**model_request):
        gateway["requests"].append(model_request)

        if gateway["error"] is not None:
            raise gateway["error"]

        return gateway["response"]

    module.chat_completion = chat_completion
    module.ModelGatewayError = RuntimeError
    sys.modules["agents.runtime.model_gateway"] = module

    return gateway


GATEWAY = _install_stubs()

from agents.broker.contracts import AgentRequest, HistoryEntry, Ref  # noqa: E402
from agents.responder import agent  # noqa: E402

CONTEXT = {"user_id": 7, "now": "2026-09-23T09:00:00", "tz": "Europe/Kyiv", "locale": "uk"}


def _completion(text):
    """The shape the OpenAI SDK returns, as far as the responder reads it."""
    message = types.SimpleNamespace(content=text)

    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


def _request(history=(), message="save this"):
    return AgentRequest(
        request_id="r1",
        correlation_id="c1",
        causation_id="s1",
        agent="responder",
        message=message,
        context=CONTEXT,
        history=tuple(history),
        hops_left=1)


SAVED_NOTE = HistoryEntry("enrich", "done", produced=(Ref("note", "12"),), state_id="s1")
FAILED_HOP = HistoryEntry("reminder", "failed", error="no time found", state_id="s2")


class ModelReplyTests(unittest.TestCase):
    def setUp(self):
        GATEWAY["error"] = None
        GATEWAY["requests"].clear()

    def test_the_model_reply_is_used_when_it_comes_back(self):
        GATEWAY["response"] = _completion("Saved your note.")

        result = agent.start(_request([SAVED_NOTE]))

        self.assertEqual("done", result.status)
        self.assertEqual("Saved your note.", result.reply)
        self.assertFalse(result.state["fallback"])

    def test_the_prompt_carries_the_record_not_agent_prose(self):
        GATEWAY["response"] = _completion("ok")

        agent.start(_request([SAVED_NOTE, FAILED_HOP]))

        sent = GATEWAY["requests"][0]["messages"][1]["content"]
        self.assertIn("enrich: done, produced note 12", sent)
        self.assertIn("reminder: failed", sent)
        self.assertIn("no time found", sent)
        self.assertIn("uk", sent, "the reply language travels with the prompt")

    def test_a_suspended_turn_tells_the_model_who_is_waiting(self):
        """Read from the history, not handed over by the broker — the responder
        gets no channel the other agents do not have."""
        GATEWAY["response"] = _completion("ok")
        paused = HistoryEntry("reminder", "needs_input", state_id="s2")

        agent.start(_request([SAVED_NOTE, paused]))

        sent = GATEWAY["requests"][0]["messages"][1]["content"]
        self.assertIn("reminder is waiting for the user to confirm", sent)

    def test_a_finished_turn_says_nothing_about_waiting(self):
        GATEWAY["response"] = _completion("ok")

        agent.start(_request([SAVED_NOTE]))

        self.assertNotIn("waiting", GATEWAY["requests"][0]["messages"][1]["content"])


class FallbackTests(unittest.TestCase):
    """The responder must not be able to lose a turn's outcome."""

    def setUp(self):
        GATEWAY["error"] = None
        GATEWAY["requests"].clear()

    def test_a_model_failure_still_reports_what_was_saved(self):
        GATEWAY["error"] = RuntimeError("model_rate_limited")

        result = agent.start(_request([SAVED_NOTE]))

        self.assertEqual("done", result.status, "a failed reply is not a failed turn")
        self.assertEqual("Enrich saved 1 note.", result.reply)
        self.assertTrue(result.state["fallback"])
        self.assertIn("model_rate_limited", result.state["error"])

    def test_the_fallback_counts_rather_than_leaking_internal_ids(self):
        """The user gets "1 note", not "note 12" — the id is a database key,
        not something to read out."""
        GATEWAY["error"] = RuntimeError("down")

        result = agent.start(_request([SAVED_NOTE]))

        self.assertNotIn("12", result.reply)

    def test_an_empty_completion_falls_back_rather_than_replying_blank(self):
        GATEWAY["response"] = _completion("   ")

        result = agent.start(_request([SAVED_NOTE]))

        self.assertTrue(result.reply.strip())
        self.assertTrue(result.state["fallback"])

    def test_the_fallback_counts_each_kind(self):
        history = (HistoryEntry(
            "enrich", "done",
            produced=(Ref("note", "1"), Ref("link", "1-2"), Ref("link", "1-3"))),)

        self.assertEqual("Enrich saved 1 note, 2 links.", agent.write_fallback(history))

    def test_the_fallback_names_a_failure(self):
        self.assertIn("reminder failed", agent.write_fallback((FAILED_HOP,)).lower())

    def test_the_fallback_says_something_when_nothing_ran(self):
        self.assertEqual(agent.NOTHING_HAPPENED, agent.write_fallback(()))

    def test_the_fallback_ignores_the_responders_own_hop(self):
        """The responder is in the history by the time a later reader sees it;
        it must not report on itself."""
        history = (SAVED_NOTE, HistoryEntry("responder", "done"))

        self.assertNotIn("responder", agent.write_fallback(history))


class SpecTests(unittest.TestCase):
    def test_it_is_never_a_routing_candidate(self):
        self.assertEqual((), agent.SPEC.entry_tools)

    def test_it_may_read_every_agents_state(self):
        self.assertEqual(("*",), agent.SPEC.may_read)

    def test_it_never_pauses_so_it_needs_no_resume(self):
        self.assertIsNone(agent.SPEC.resume)


if __name__ == "__main__":
    unittest.main()
