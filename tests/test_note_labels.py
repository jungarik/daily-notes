"""The web app labels a note with its own words, not with its title.

`notes.title` is an LLM's one-line summary written by enrichment. It still
exists and the bot still shows it, but every browsing surface in the Mini App
now reads the start of the note's own `text` instead: a list of titles is a
list of the model's words where the user is looking for their own.

One section is deliberately exempt. `mapview` draws cards a few dozen pixels
wide, where a 60-character opening is unreadable and a summary is the only
thing that fits — so it keeps `_display_title`, and this file asserts that the
exception stays exactly one section wide.

The label itself runs for real; the payload key and the client's use of it are
read from source, since what matters there is which name each side spells.
"""

import re
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
WEBAPP = ROOT / "browser" / "webapp" / "src"
LABELLED = ("feed", "explorer", "notesheet", "search")


def _helper(section: str):
    """A section's helper with the shared pool stubbed just long enough."""
    stubbed = []

    for name in ("db", "psycopg", "file_store"):
        if name not in sys.modules:
            stub = types.ModuleType(name)
            stub.cursor = lambda: None
            sys.modules[name] = stub
            stubbed.append(name)

    try:
        module = __import__(f"api.{section}.helper", fromlist=["helper"])
    finally:
        for name in stubbed:
            sys.modules.pop(name, None)

    for name in list(sys.modules):
        if name.startswith("api."):
            sys.modules.pop(name, None)

    return module


class LabelTests(unittest.TestCase):
    """`_note_label`, run in each of the four sections that owns a copy."""

    def _label(self, section, text, **kwargs):
        return _helper(section)._note_label(text, **kwargs)

    def test_a_short_note_is_its_whole_text(self):
        for section in LABELLED:
            with self.subTest(section=section):
                self.assertEqual("buy milk", self._label(section, "buy milk"))

    def test_a_long_note_is_cut_with_an_ellipsis(self):
        for section in LABELLED:
            with self.subTest(section=section):
                label = self._label(section, "word " * 40)

                self.assertTrue(label.endswith("…"), label)
                self.assertEqual(61, len(label))

    def test_whitespace_is_collapsed_first(self):
        """A note that opens with a newline would otherwise render as a blank
        row — the label would be whitespace and the row would look broken."""
        for section in LABELLED:
            with self.subTest(section=section):
                self.assertEqual("first line second",
                                 self._label(section, "\n\n  first line\n  second  "))

    def test_a_note_with_no_text_is_untitled(self):
        """Not an empty string: a note that is only photos still needs a name
        in a list of rows. This is the *only* way "untitled" can appear now."""
        for section in LABELLED:
            with self.subTest(section=section):
                self.assertEqual("untitled", self._label(section, ""))
                self.assertEqual("untitled", self._label(section, None))
                self.assertEqual("untitled", self._label(section, "   \n "))

    def test_every_section_cuts_at_the_same_length(self):
        """So a link chip, an explorer row, a search hit and a linked note in
        the sheet all read alike."""
        for section in LABELLED:
            with self.subTest(section=section):
                source = (ROOT / "api" / section / "helper.py").read_text(encoding="utf-8")

                self.assertIn("LABEL_CHARS = 60", source)

    def test_the_label_takes_only_the_text(self):
        """The whole point, pinned at the signature: a parameter for the title
        would invite the next reader to pass one, and the fallback inside is
        the word "untitled" rather than a title."""
        for section in LABELLED:
            with self.subTest(section=section):
                source = (ROOT / "api" / section / "helper.py").read_text(encoding="utf-8")

                self.assertIn("def _note_label(text: str | None, limit: int = LABEL_CHARS)",
                              source)
                self.assertNotIn('(title or "")', source)
                self.assertNotIn('b["title"]', source)
                self.assertNotIn('n["title"]', source)


class PayloadTests(unittest.TestCase):
    def test_the_field_is_called_label(self):
        """`title` would have been a lie: the value is a cut of the text."""
        for section in LABELLED:
            with self.subTest(section=section):
                schemas = (ROOT / "api" / section / "schemas.py").read_text(encoding="utf-8")

                self.assertIn("label: str", schemas)
                self.assertNotIn("title: str", schemas)

    def test_the_title_column_is_no_longer_selected(self):
        """Dead data flowing through a payload reads as a live field."""
        for section in LABELLED:
            with self.subTest(section=section):
                sql = (ROOT / "api" / section / "db.py").read_text(encoding="utf-8")
                selects = re.findall(r"SELECT[^;]*", sql, re.IGNORECASE)

                for statement in selects:
                    self.assertNotIn("n.title", statement)
                    self.assertNotIn(", title", statement)

    def test_search_still_matches_on_the_title(self):
        """Shown and searched are different questions: an enriched title often
        holds a word the note itself does not, and dropping it from the
        predicate would make those notes unfindable. The consequence — a hit
        can match text the row does not display — is documented there."""
        sql = (ROOT / "api" / "search" / "db.py").read_text(encoding="utf-8")

        self.assertIn("coalesce(title, '') ILIKE", sql)


class MapViewExemptionTests(unittest.TestCase):
    def test_the_map_keeps_the_enriched_title(self):
        """Its cards are a few dozen pixels wide: a 60-character opening is
        unreadable there and the summary is the only thing that fits."""
        helper = (ROOT / "api" / "mapview" / "helper.py").read_text(encoding="utf-8")
        schemas = (ROOT / "api" / "mapview" / "schemas.py").read_text(encoding="utf-8")

        self.assertIn("_display_title", helper)
        self.assertIn("title", schemas)

    def test_the_exemption_is_one_section_wide(self):
        """Nothing else may keep the old mapper."""
        keeping = [path.parent.name
                   for path in (ROOT / "api").glob("*/helper.py")
                   if "_display_title" in path.read_text(encoding="utf-8")]

        self.assertEqual(["mapview"], keeping)


class ClientTests(unittest.TestCase):
    SURFACES = {
        "components/NoteCard.jsx": ("it.label", "name: detail.label"),
        "components/Explorer.jsx": ("note.label",),
        "components/Search.jsx": ("n.label",),
        "components/Chat.jsx": ("label: n.label",),
    }

    def test_each_surface_reads_the_label(self):
        for name, expected in self.SURFACES.items():
            source = (WEBAPP / name).read_text(encoding="utf-8")

            for needle in expected:
                with self.subTest(file=name, needle=needle):
                    self.assertIn(needle, source)

    # `MapView.jsx` and `engine.js` are fed by the exempt section;
    # `NoteMiniCard.jsx` serves both and accepts either key. `Chat.jsx` keeps
    # one `c.title`, and it is not this change's business: those link
    # candidates come from the **agent farm**, which labels a note with
    # `common.helper.note_label` and is a different surface from the read
    # sections. Worth knowing it is the last title the app displays outside
    # the map.
    TITLE_ALLOWED = ("MapView.jsx", "engine.js", "NoteMiniCard.jsx", "Chat.jsx")

    def test_no_read_surface_still_reads_a_title(self):
        offending = []

        for path in list(WEBAPP.rglob("*.jsx")) + list(WEBAPP.rglob("*.js")):
            if path.name in self.TITLE_ALLOWED:
                continue

            if re.search(r"\.title\b|\btitle:", path.read_text(encoding="utf-8")):
                offending.append(path.name)

        self.assertEqual([], offending)

    def test_the_chat_title_is_the_agent_farms_and_only_that(self):
        """So the exemption cannot quietly widen: one occurrence, in the link
        picker that renders an agent's candidates."""
        source = (WEBAPP / "components/Chat.jsx").read_text(encoding="utf-8")
        code = re.sub(r"//[^\n]*", "", source)

        self.assertEqual(1, len(re.findall(r"\.title\b", code)))
        self.assertIn('className="link-opt-title">{c.title', code)

    def test_the_mini_card_accepts_either(self):
        """It is shared: the chat passes a `label` from the notesheet section,
        the map passes a `title` from its own. One component, two callers, and
        the fallback is what lets the map stay exempt."""
        source = (WEBAPP / "components/NoteMiniCard.jsx").read_text(encoding="utf-8")

        self.assertIn("note.label || note.title", source)

    def test_the_untitled_fallbacks_are_gone(self):
        """The server never sends an empty label, so a client-side `||
        "untitled"` is a second answer to a question already answered — and
        the kind of dead branch that reads as a live feature."""
        for name in ("components/Explorer.jsx", "components/Search.jsx",
                     "components/NoteCard.jsx"):
            with self.subTest(file=name):
                # Comments stripped: one of them explains where "untitled"
                # now comes from, which is not a fallback.
                source = re.sub(r"//[^\n]*", "",
                                (WEBAPP / name).read_text(encoding="utf-8"))

                self.assertNotIn('"untitled"', source)

    def test_the_explorer_sorts_by_the_label(self):
        """Worth stating because it changes the tree's order: rows now sort by
        how each note opens, not by an enriched title."""
        source = (WEBAPP / "components/Explorer.jsx").read_text(encoding="utf-8")

        self.assertIn(".localeCompare(b.label", source)
        self.assertIn("a.label ||", source)


if __name__ == "__main__":
    unittest.main()
