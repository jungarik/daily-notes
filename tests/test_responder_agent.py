"""The responder: the one agent that writes to the user.

The model gateway is stubbed, so this covers what the responder promises the
farm — that it never fails, and that it reports the record rather than inventing
one — without an API key or a network call.
"""

import sys
import types
import unittest

from tests import gateway_stub


def _install_stubs():
    """Stand in for the model gateway, which reaches `openai` at import time.

    Idempotent and shared: more than one test module stubs this, and the last
    one to install must not orphan the handle an earlier one already gave to an
    agent module it imported. Reusing the same recorder keeps every file
    pointing at one stub however the suite is ordered.
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


def _install_state_rows():
    """Stand in for `tools.responder.db`, which reaches psycopg at import time.

    Idempotent and shared for the same reason the gateway stub is: more than one
    test module installs it, and the loser of that race must not be left holding
    a dict nothing reads. The real tool still runs — only the SQL is stood in
    for, so the allowlist and the error shapes are exercised for real.
    """
    existing = sys.modules.get("tools.responder.db")

    if existing is not None and hasattr(existing, "ROWS"):
        return existing.ROWS

    rows = {}

    module = types.ModuleType("tools.responder.db")
    module.get_state = lambda state_id, user_id: rows.get((str(state_id), user_id))
    module.ROWS = rows
    sys.modules["tools.responder.db"] = module

    return rows


GATEWAY = gateway_stub.install()
STATES = _install_state_rows()

from agents.contracts import AgentRequest, HistoryEntry, Ref  # noqa: E402
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
        STATES.clear()

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
        """Read from the history, not handed over by the loop — the responder
        gets no channel the other agents do not have."""
        GATEWAY["response"] = _completion("ok")
        paused = HistoryEntry("reminder", "needs_input", state_id="s2")

        agent.start(_request([SAVED_NOTE, paused]))

        sent = GATEWAY["requests"][0]["messages"][1]["content"]
        self.assertIn("reminder is waiting for the user to confirm", sent)

    def test_a_suspended_turn_carries_the_action_being_confirmed(self):
        """Naming the waiting agent is not enough. The app is already showing
        Confirm/Cancel, so a reply that cannot say what is being confirmed
        strands the user — the summary the agent saved has to reach the model."""
        GATEWAY["response"] = _completion("ok")
        STATES[("s2", 7)] = {
            "agent": "reminder",
            "status": "needs_input",
            "state": {"planned": {"summary": "Remind you about the dentist at 9am"}},
        }
        paused = HistoryEntry("reminder", "needs_input", state_id="s2")

        agent.start(_request([SAVED_NOTE, paused]))

        sent = GATEWAY["requests"][0]["messages"][1]["content"]
        self.assertIn("Remind you about the dentist at 9am", sent)

    def test_a_confirmation_with_no_summary_still_shows_the_action(self):
        """An agent that paused without writing a summary must not turn into a
        bare "something is waiting" — the raw proposal is better than nothing."""
        GATEWAY["response"] = _completion("ok")
        STATES[("s2", 7)] = {
            "agent": "reminder",
            "status": "needs_input",
            "state": {"planned": {"name": "create_reminder", "args": {"at": "09:00"}}},
        }
        paused = HistoryEntry("reminder", "needs_input", state_id="s2")

        agent.start(_request([SAVED_NOTE, paused]))

        self.assertIn("create_reminder", GATEWAY["requests"][0]["messages"][1]["content"])

    def test_a_finished_turn_says_nothing_about_waiting(self):
        GATEWAY["response"] = _completion("ok")

        agent.start(_request([SAVED_NOTE]))

        self.assertNotIn("waiting", GATEWAY["requests"][0]["messages"][1]["content"])


class ReadStateTests(unittest.TestCase):
    """The history carries refs, not prose. An answer another agent composed is
    only reachable through `read_state` — without it a Q&A turn could only be
    reported as "found some notes"."""

    def setUp(self):
        GATEWAY["error"] = None
        GATEWAY["requests"].clear()
        GATEWAY["response"] = _completion("ok")
        STATES.clear()

    def test_an_earlier_hops_answer_reaches_the_prompt(self):
        STATES[("s1", 7)] = {
            "agent": "enrich",
            "status": "done",
            "state": {"answer": "You wrote about Postgres tuning."},
        }

        agent.start(_request([SAVED_NOTE]))

        sent = GATEWAY["requests"][0]["messages"][1]["content"]
        self.assertIn("What enrich produced:", sent)
        self.assertIn("Postgres tuning", sent)

    def test_an_unreadable_state_costs_detail_not_the_reply(self):
        """No row for that id — the turn must still produce a reply."""
        result = agent.start(_request([SAVED_NOTE]))

        self.assertEqual("done", result.status)
        self.assertTrue(result.reply)
        self.assertNotIn("What enrich produced:",
                         GATEWAY["requests"][0]["messages"][1]["content"])

    def test_a_markered_answer_reaches_the_prompt_with_its_markers(self):
        """`[[note:ID]]` is the reference itself — the client turns each one into
        a note card. The responder rewrites the prose around it, so the markers
        have to survive both the read and the prompt, and the system prompt has
        to say to carry them through."""
        STATES[("s1", 7)] = {
            "agent": "finder",
            "status": "done",
            "state": {"answer": "Two on tuning:\n[[note:12]]\n[[note:34]]"},
        }

        agent.start(_request([SAVED_NOTE]))

        model_request = GATEWAY["requests"][0]
        self.assertIn("[[note:12]]", model_request["messages"][1]["content"])
        self.assertIn("[[note:34]]", model_request["messages"][1]["content"])
        self.assertIn("[[note:ID]]", model_request["messages"][0]["content"])

    def test_it_does_not_read_its_own_hop(self):
        """The responder is in the history on a resumed turn; reporting on its
        own earlier reply would have it quoting itself."""
        STATES[("s9", 7)] = {
            "agent": "responder",
            "status": "done",
            "state": {"reply": "an earlier reply"},
        }
        history = (SAVED_NOTE, HistoryEntry("responder", "done", state_id="s9"))

        agent.start(_request(history))

        self.assertNotIn("an earlier reply",
                         GATEWAY["requests"][0]["messages"][1]["content"])


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
