"""The v2 chat section's shaping: turn outcomes as responses, and the transcript.

Everything here is pure — the endpoint owns the I/O — so this runs without
FastAPI, a database or an agent. Pydantic is stubbed only when it is missing, so
the models are the real ones wherever they can be.
"""

import sys
import types
import unittest


def _stub_pydantic_if_absent():
    """A BaseModel that keeps kwargs as attributes and falls back to defaults.

    Class-level defaults (`status: str = "answer"`) are found by ordinary
    attribute lookup, which is the whole of what the response models rely on
    here.
    """
    try:
        import pydantic  # noqa: F401

        return
    except Exception:
        pass

    class BaseModel:
        def __init__(self, **fields):
            for name, value in fields.items():
                setattr(self, name, value)

    module = types.ModuleType("pydantic")
    module.BaseModel = BaseModel
    module.Field = lambda *args, **kwargs: None
    sys.modules["pydantic"] = module


_stub_pydantic_if_absent()

from api.chat_v2 import helper  # noqa: E402


class ResponseTests(unittest.TestCase):
    def test_a_finished_turn_is_an_answer(self):
        response = helper.turn_response(3, "done", "Saved your note.", None)

        self.assertEqual("answer", response.status)
        self.assertEqual("Saved your note.", response.reply)
        self.assertIsNone(response.action)

    def test_a_suspended_turn_is_a_confirm_carrying_the_action(self):
        pending = {"ask": {
            "kind": "confirm",
            "action": {"name": "create_note", "args": {"text": "x"}},
            "summary": "Create a note",
        }}

        response = helper.turn_response(3, "needs_input", "About to save…", pending)

        self.assertEqual("confirm", response.status)
        self.assertEqual("create_note", response.action.name)
        self.assertEqual("Create a note", response.action.summary)

    def test_a_select_action_keeps_its_kind_so_the_client_renders_a_picker(self):
        pending = {"ask": {
            "kind": "select",
            "action": {"name": "link_notes", "args": {"candidates": [1, 2]}},
            "summary": "Link these",
        }}

        response = helper.turn_response(3, "needs_input", None, pending)

        self.assertEqual("select", response.action.kind)
        self.assertEqual([1, 2], response.action.args["candidates"])

    def test_a_failed_turn_still_answers_rather_than_returning_nothing(self):
        """The responder cannot fail, so a reply-less turn is a real fault — but
        the user gets a sentence either way."""
        response = helper.turn_response(3, "failed", None, None)

        self.assertEqual("answer", response.status)
        self.assertEqual(helper.NO_REPLY, response.reply)

    def test_an_action_summary_falls_back_to_the_actions_own(self):
        pending = {"ask": {"action": {"name": "create_note", "summary": "inner"}}}

        response = helper.turn_response(3, "needs_input", None, pending)

        self.assertEqual("inner", response.action.summary)


class PendingTests(unittest.TestCase):
    """v1 and v2 share the `chat_threads` row but not the shape of `pending`."""

    def test_a_broker_handle_is_resumable(self):
        pending = {"correlation_id": "c1", "agent": "enrich", "token": "{}"}

        self.assertEqual(pending, helper.find_resumable(pending))

    def test_a_v1_pending_is_not_mistaken_for_one(self):
        """v1 stores a handed-off action with a `tool_call_id`. Reading that as
        a turn handle would raise on a key that was never written."""
        self.assertIsNone(helper.find_resumable(
            {"tool_call_id": "call_1", "action": {"name": "create_note"}}))

    def test_nothing_pending_is_not_resumable(self):
        self.assertIsNone(helper.find_resumable(None))
        self.assertIsNone(helper.find_resumable({}))


class TranscriptTests(unittest.TestCase):
    """The broker returns no messages, so the section keeps the thread itself."""

    def test_a_turn_appends_the_question_and_the_answer(self):
        messages = helper.append_turn([], "where is it?", "Right here.")

        self.assertEqual(
            [{"role": "user", "content": "where is it?"},
             {"role": "assistant", "content": "Right here."}],
            messages)

    def test_a_confirm_adds_only_the_second_reply(self):
        """The user's request is already in the thread from the turn that
        suspended; repeating it would show the question twice."""
        existing = [{"role": "user", "content": "save this"}]

        messages = helper.append_turn(existing, None, "Saved.")

        self.assertEqual(2, len(messages))
        self.assertEqual("assistant", messages[-1]["role"])

    def test_the_loaded_list_is_never_edited_in_place(self):
        existing = [{"role": "user", "content": "one"}]

        helper.append_turn(existing, "two", "three")

        self.assertEqual(1, len(existing))

    def test_no_reply_leaves_the_transcript_without_a_blank_assistant_turn(self):
        messages = helper.append_turn([], "asked", None)

        self.assertEqual(1, len(messages))


class LastMessageTests(unittest.TestCase):
    def test_the_most_recent_user_message_is_what_a_confirm_carries(self):
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "remind me tomorrow"},
        ]

        self.assertEqual("remind me tomorrow", helper.find_last_user_message(messages))

    def test_an_empty_thread_yields_an_empty_message_not_an_error(self):
        self.assertEqual("", helper.find_last_user_message([]))


class ContextTests(unittest.TestCase):
    def test_the_context_is_json_safe_for_the_state_store(self):
        """Every agent state row is JSON, so the clock travels as a string."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        context = helper.build_context(
            7, datetime(2026, 9, 23, 9, 0), ZoneInfo("Europe/Kyiv"), "uk")

        self.assertEqual(7, context["user_id"])
        self.assertEqual("2026-09-23T09:00:00", context["now"])
        self.assertEqual("Europe/Kyiv", context["tz"])
        self.assertEqual("uk", context["locale"])


if __name__ == "__main__":
    unittest.main()
