"""The note card shows no title.

`title` is an LLM-written one-line summary of the note, and the card already
renders the note's full text underneath — so the heading said the same thing
twice, in different words, and the second-best version came first. Removing it
is the point of this file: the card opens on its date and path.

The title itself is not gone from the data. `openCtx` still passes it as the
context menu's `name`, which is what makes the delete sheet read
`Delete "my note"?` instead of `Delete "note"?`, and the mini cards on the map
have nothing but a title to show. Both are asserted here, because "remove the
title" is easy to over-apply.

Read from source: the question is what the template renders, and these are the
cheapest assertions that answer it without a browser.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
WEBAPP = ROOT / "browser" / "webapp" / "src"
CARD_PATH = WEBAPP / "components" / "NoteCard.jsx"
CARD = CARD_PATH.read_text(encoding="utf-8")
CSS = (WEBAPP / "styles.css").read_text(encoding="utf-8")


class NoteCardTitleTests(unittest.TestCase):
    def test_the_card_renders_no_title(self):
        """`card-title` is the shared heading class. The card must not take it
        — not in the post head, not anywhere else in the template."""
        self.assertNotIn('className="card-title"', CARD)

    def test_the_card_does_not_render_the_title_field(self):
        """A heading rebuilt out of the note's label under another class name
        would pass the assertion above while putting a heading back."""
        self.assertNotIn("detail.label}</div>", CARD)
        self.assertNotIn('"card-title"', CARD)

    def test_the_filename_suffix_is_gone_with_it(self):
        """The heading read `<title>.md`. Nothing else in the card appends it,
        so a surviving `.md"` means the heading survived too."""
        self.assertNotIn('+ ".md"', CARD)

    def test_the_date_keeps_a_row_of_its_own(self):
        """It used to be a span nested inside the title. With the title gone it
        is the post head's own child, which is also what keeps the dots in the
        top-right corner rather than letting them rise into the carousel."""
        self.assertIn('<div className="card-date">{dt}</div>', CARD)
        self.assertIn(".post-head .card-date {", CSS)

    def test_the_date_is_no_longer_scoped_to_the_title(self):
        """The old rule only applied inside `.card-title`, so leaving it would
        style nothing while looking like it still worked."""
        self.assertNotIn(".card-title .card-date", CSS)

    def test_the_date_row_takes_the_free_space(self):
        """`.post-head` is a flex row and the dots are `flex: none`. Something
        has to claim the slack or they slide left to meet the date."""
        start = CSS.index(".post-head .card-date {")
        rule = CSS[start:CSS.index("}", start)]

        self.assertIn("flex: 1", rule)

    def test_the_context_menu_names_the_note_by_its_label(self):
        """The delete sheet quotes this name back at the user, so it gets the
        same label every other surface shows — the note's own opening words.
        It used to read `detail.title`, which is the one thing the app no
        longer displays anywhere outside the map."""
        self.assertIn("name: detail.label", CARD)
        self.assertNotIn("detail.title", CARD)

    def test_the_shared_title_class_still_exists_for_the_sheets(self):
        """`card-title` is not the card's alone — the change-path and delete
        sheets and the folder filter head all take it, so the rule stays."""
        self.assertIn(".card-title {", CSS)

    def test_the_map_mini_cards_keep_their_titles(self):
        """A map node has no text body to fall back on: a title-less mini card
        is a blank rectangle."""
        mini = (WEBAPP / "components" / "NoteMiniCard.jsx").read_text(encoding="utf-8")

        self.assertIn("note-mini-title", mini)


if __name__ == "__main__":
    unittest.main()
