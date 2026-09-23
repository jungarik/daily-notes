"""The `read_state` tool: how an agent gets more than the history gives it.

The database module is stubbed, so this covers the tenancy guard, the `may_read`
allowlist and the error shapes without a Postgres connection.
"""

import sys
import types
import unittest


def _install_state_rows():
    """Stand in for `tools.broker.db`, which reaches psycopg at import time.

    Idempotent and shared for the same reason the gateway stub is: more than one
    test module installs it, and the loser of that race must not be left holding
    a dict nothing reads. The real tool still runs — only the SQL is stood in
    for, so the allowlist and the error shapes are exercised for real.
    """
    existing = sys.modules.get("tools.broker.db")

    if existing is not None and hasattr(existing, "ROWS"):
        return existing.ROWS

    rows = {}

    module = types.ModuleType("tools.broker.db")
    module.get_state = lambda state_id, user_id: rows.get((str(state_id), user_id))
    module.ROWS = rows
    sys.modules["tools.broker.db"] = module

    return rows


ROWS = _install_state_rows()

from agents.contracts import ToolResult  # noqa: E402
from tools.broker import read_state  # noqa: E402


class MayReadTests(unittest.TestCase):
    def test_the_wildcard_reads_anyone(self):
        self.assertTrue(read_state.may_read(("*",), "enrich"))

    def test_a_named_agent_is_allowed(self):
        self.assertTrue(read_state.may_read(("conversation", "enrich"), "enrich"))

    def test_an_unnamed_agent_is_refused(self):
        self.assertFalse(read_state.may_read(("conversation",), "enrich"))

    def test_an_empty_allowlist_reads_nothing(self):
        self.assertFalse(read_state.may_read((), "enrich"))
        self.assertFalse(read_state.may_read(None, "enrich"))


class InvokeTests(unittest.TestCase):
    def setUp(self):
        ROWS.clear()
        ROWS[("s1", 7)] = {
            "agent": "finder",
            "status": "done",
            "state": {"answer": "You wrote about Postgres tuning."},
        }

    def test_an_allowed_read_returns_the_state_as_saved(self):
        result = read_state.invoke(
            {"user_id": 7, "agent": "responder", "may_read": ("*",)},
            {"state_id": "s1"})

        self.assertIsInstance(result, ToolResult)
        self.assertEqual("finder", result.data["agent"])
        self.assertEqual(
            "You wrote about Postgres tuning.", result.data["state"]["answer"])

    def test_an_allowlist_that_excludes_the_writer_refuses(self):
        result = read_state.invoke(
            {"user_id": 7, "agent": "reminder", "may_read": ("conversation",)},
            {"state_id": "s1"})

        self.assertIn("not allowed", result.data["error"])

    def test_a_refusal_never_leaks_what_the_row_held(self):
        """The error names the agent that was refused, never its state."""
        result = read_state.invoke(
            {"user_id": 7, "agent": "reminder", "may_read": ()},
            {"state_id": "s1"})

        self.assertNotIn("Postgres", str(result.data))
        self.assertNotIn("answer", str(result.data))

    def test_another_users_state_is_not_found_whatever_the_allowlist(self):
        """Tenancy is checked in SQL, so the wildcard cannot cross an owner."""
        result = read_state.invoke(
            {"user_id": 99, "agent": "responder", "may_read": ("*",)},
            {"state_id": "s1"})

        self.assertIn("not found", result.data["error"])

    def test_an_unknown_state_id_is_an_error_not_a_crash(self):
        result = read_state.invoke(
            {"user_id": 7, "agent": "responder", "may_read": ("*",)},
            {"state_id": "nonesuch"})

        self.assertIn("not found", result.data["error"])

    def test_a_missing_state_id_is_rejected(self):
        result = read_state.invoke(
            {"user_id": 7, "agent": "responder", "may_read": ("*",)}, {})

        self.assertIn("state_id", result.data["error"])

    def test_a_missing_owner_is_rejected(self):
        result = read_state.invoke({"agent": "responder"}, {"state_id": "s1"})

        self.assertIn("user_id", result.data["error"])


class RegistrationTests(unittest.TestCase):
    def test_it_is_a_context_tool_the_model_is_never_offered(self):
        """A deterministic read: a node calls it, the allowlist in
        `execute_allowed_tool` keeps a model-driven path out."""
        from tools import broker

        self.assertIn("read_state", broker.TOOLS)
        self.assertIn("read_state", broker.CONTEXT_TOOLS)
        self.assertEqual([], broker.TOOL_SPECS)
        self.assertEqual(set(), broker.WRITE_TOOLS)


if __name__ == "__main__":
    unittest.main()
