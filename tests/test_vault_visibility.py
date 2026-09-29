"""What the vault shows, and what it deliberately does not.

Two rules, both enforced in SQL because that is where they live:

* A note with no `path` is not in the vault yet. Every browsing view omits it;
  the bot and the chat agents still see it, so it stays recoverable and one
  enrichment away from appearing properly.
* "Upcoming" reminders are the ones still to come. A reminder left `scheduled`
  past its time was never delivered and will not fire on its own — listing it
  as upcoming is a statement the user acts on.

The queries are read as text: they run against Postgres, and what matters here
is that no section quietly omits the clause, which is a property of the source.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]

# The four sections a person browses their vault through.
VAULT_SECTIONS = ("feed", "explorer", "mapview", "search")

# Reachable on purpose: a note must stay findable and openable by id, or an
# un-filed one has no way back and a [[note:ID]] marker 404s.
REACHABLE = ("notesheet", "notecard")


def _sql(path):
    return path.read_text(encoding="utf-8")


def _has_path_filter(sql: str) -> bool:
    return re.search(r"path IS NOT NULL AND \w*\.?path <> ''", sql) is not None


class VaultViewTests(unittest.TestCase):
    def test_every_browsing_section_filters_un_filed_notes(self):
        for section in VAULT_SECTIONS:
            with self.subTest(section=section):
                self.assertTrue(
                    _has_path_filter(_sql(ROOT / "api" / section / "db.py")),
                    f"api/{section} would show notes that are not in the vault")

    def test_the_map_filters_its_edges_too(self):
        """Map nodes are derived from edges, so an edge to an un-filed note
        draws a node whose detail never arrives."""
        sql = _sql(ROOT / "api" / "mapview" / "db.py")
        links = sql.split("def all_links", 1)[1].split("def ", 1)[0]

        self.assertIn("a.path IS NOT NULL", links)
        self.assertIn("b.path IS NOT NULL", links)

    def test_opening_a_note_by_id_is_not_filtered(self):
        """Hiding a note from the tree must not make it unopenable: the chat
        renders [[note:ID]] cards through these."""
        for section in REACHABLE:
            with self.subTest(section=section):
                self.assertFalse(_has_path_filter(_sql(ROOT / "api" / section / "db.py")))

    def test_the_agents_and_the_bot_still_see_everything(self):
        """An un-filed note is recoverable precisely because these do not
        filter it — the chat can find it and offer to file it.

        `list_paths` is exempt and always was: it answers "which folders exist",
        so a note with no folder is not one of its rows. Checking the whole file
        would fail on that and teach nobody anything."""
        for path, retrieval in ((ROOT / "tools" / "finder" / "db.py", "search_chunks"),
                                (ROOT / "api" / "telegram_bot" / "db.py", "search_chunks")):
            sql = _sql(path)
            body = sql.split(f"def {retrieval}", 1)[1].split("\ndef ", 1)[0]

            with self.subTest(source=f"{path.name}:{retrieval}"):
                self.assertFalse(_has_path_filter(body))


class UpcomingReminderTests(unittest.TestCase):
    def _upcoming(self, path, name="upcoming_reminders"):
        return _sql(path).split(f"def {name}", 1)[1].split("\ndef ", 1)[0]

    def test_both_upcoming_listings_require_a_future_time(self):
        for path in (ROOT / "tools" / "finder" / "db.py",
                     ROOT / "api" / "telegram_bot" / "db.py"):
            with self.subTest(source=path.name):
                body = self._upcoming(path)

                self.assertIn("status IN ('scheduled', 'postponed')", body)
                self.assertIn("remind_at >= now()", body)

    def test_the_count_agrees_with_the_list(self):
        """Otherwise the bot reports three upcoming reminders and shows one."""
        body = self._sql_count()

        self.assertIn("status IN ('scheduled', 'postponed')", body)
        self.assertIn("remind_at >= now()", body)

    def _sql_count(self):
        sql = _sql(ROOT / "api" / "telegram_bot" / "db.py")
        return sql.split("def count_active", 1)[1].split("\ndef ", 1)[0]

    def test_the_agenda_keeps_its_own_range(self):
        """Agenda answers a question about a window — including a past one.
        `now()` there would silently empty "what did I have yesterday"."""
        body = _sql(ROOT / "tools" / "finder" / "db.py")
        agenda = body.split("def agenda_reminders", 1)[1].split("\ndef ", 1)[0]

        self.assertIn("r.remind_at >= %s AND r.remind_at < %s", agenda)
        self.assertNotIn("now()", agenda)

    def test_the_dispatcher_still_claims_what_is_due(self):
        """The opposite direction, and the one thing that must not gain a
        future filter: it exists to pick up reminders whose time has come."""
        sql = _sql(ROOT / "api" / "telegram_bot" / "db.py")
        claim = sql.split("def claim_due_reminders", 1)[1].split("\ndef ", 1)[0]

        self.assertIn("remind_at <= %s", claim)


class NoStaleFallbackTests(unittest.TestCase):
    def test_the_client_no_longer_invents_a_folder(self):
        """`default_root` existed to label a note with no path. Those never
        reach the client now, so the branch could not fire — and a branch no
        input can reach reads as a live feature to the next person."""
        client = ROOT / "browser" / "webapp" / "src"
        offending = [
            str(path.relative_to(ROOT))
            for path in list(client.rglob("*.jsx")) + list(client.rglob("*.js"))
            if "defaultRoot" in path.read_text(encoding="utf-8")
        ]

        self.assertEqual([], offending)

    def test_the_explorer_payload_dropped_it_too(self):
        self.assertNotIn("default_root",
                         _sql(ROOT / "api" / "explorer" / "schemas.py"))


if __name__ == "__main__":
    unittest.main()
