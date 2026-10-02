"""The Add-note page loading an existing note for editing.

The ordering here is forced and worth stating once: the keyboard rises only for
a `focus()` inside the opening gesture, so the page opens and focuses
synchronously and the note's text can only arrive afterwards. Everything below
follows from that — the placeholder instead of a spinner (the field is already
focused and being looked at), and the guard that a late response must not
overwrite what the user typed in the gap.

Read from source: this is component state and effect wiring, the same trade
`tests/test_addnote_keyboard.py` makes for the focus path.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
WEBAPP = ROOT / "browser" / "webapp" / "src"
PAGE = (WEBAPP / "components" / "AddNote.jsx").read_text(encoding="utf-8")
API_JS = (WEBAPP / "lib" / "api.js").read_text(encoding="utf-8")
CSS = (WEBAPP / "styles.css").read_text(encoding="utf-8")
PAGE_CODE = re.sub(r"//[^\n]*|/\*(?:.|\n)*?\*/", "", PAGE)


class ReadTests(unittest.TestCase):
    def test_the_page_reads_its_own_section(self):
        """Not `/api/notesheet/{id}`, whose payload is a preview card. The
        editor's read belongs to the editor's vertical."""
        self.assertIn('apiGet("/api/addnote/" + encodeURIComponent(id))', API_JS)
        self.assertIn("fetchEditableNote", PAGE_CODE)

    def test_the_read_does_not_swallow_its_errors(self):
        """Every other read in `api.js` ends in `.catch(() => …)` and degrades
        to an empty value. This one must not: a blank editor is exactly what a
        genuinely empty note looks like, so a silent failure is unreadable."""
        start = API_JS.index("export const fetchEditableNote")
        declaration = API_JS[start:API_JS.index(";", start)]

        self.assertNotIn(".catch", declaration)

    def test_a_new_note_fetches_nothing(self):
        """The plus badge has no id to read."""
        self.assertIn('if (!open || note_id == null) { setStatus("ready"); return; }',
                      PAGE_CODE)

    def test_the_effect_reruns_for_a_different_note(self):
        """The page is always mounted and reused, so the note id changing
        while it is open has to reload."""
        self.assertEqual(2, PAGE_CODE.count("}, [open, note_id]);"))


class TypedTextTests(unittest.TestCase):
    def test_a_late_response_never_overwrites_what_was_typed(self):
        """The field is focused before the request is made, so the user can be
        typing while it is in flight. Their keystrokes are newer than the
        response; a textarea that erases itself a second after opening is the
        worst failure available here."""
        self.assertIn("setText((typed) => (typed ? typed : loaded.text || \"\"))",
                      PAGE_CODE)

    def test_a_stale_response_is_dropped(self):
        """Close and reopen on another note and both reads are in flight."""
        self.assertIn("let live = true;", PAGE_CODE)
        self.assertIn("if (!live) return;", PAGE_CODE)
        self.assertIn("return () => { live = false; };", PAGE_CODE)

    def test_the_text_is_cleared_on_every_open(self):
        """Including when switching from an edited note to a new one — the
        plus badge must give an empty editor, not the last note's body."""
        reset = PAGE_CODE.index('setText("");')
        effect = PAGE_CODE.index("}, [open, note_id]);")

        self.assertLess(reset, effect)


class FeedbackTests(unittest.TestCase):
    def test_loading_is_a_placeholder_not_a_spinner(self):
        """The field is already focused and under the user's eyes; a spinner
        elsewhere on the page would be the one thing they are not looking at.
        It also keeps the textarea enabled — disabling it drops focus on iOS,
        which costs the keyboard the gesture was for."""
        self.assertIn('placeholder={status === "loading" ? "Loading…" : "Write a note…"}',
                      PAGE_CODE)
        self.assertNotIn("disabled={status", PAGE_CODE)

    def test_a_failed_read_says_so(self):
        """An empty editor with no message is indistinguishable from a note
        whose body really is empty."""
        self.assertIn('status === "failed"', PAGE_CODE)
        self.assertIn("addnote-error", PAGE_CODE)
        self.assertIn("  .addnote-error {", CSS)

    def test_a_failed_read_leaves_the_page_open(self):
        """Being dropped back to the feed mid-gesture reads as a crash, and
        nothing is saved here anyway."""
        self.assertNotIn("closeAddNote()", PAGE_CODE[PAGE_CODE.index("fetchEditableNote"):
                                                     PAGE_CODE.index("visualViewport")])

    def test_the_error_is_in_flow_not_over_the_text(self):
        """An overlaid message would cover the text it is apologising for."""
        start = CSS.index("  .addnote-error {")
        rule = CSS[start:CSS.index("}", start)]

        self.assertNotIn("position: absolute", rule)

    def test_the_status_starts_ready(self):
        """A new note has nothing to wait for, so the page must not open
        showing "Loading…" at the one moment it is most often used."""
        self.assertIn('const [status, setStatus] = useState("ready");', PAGE_CODE)


class LoadedFieldsTests(unittest.TestCase):
    """The rest of the payload — path, tags, attachments, linked ids.

    Held in state and not yet rendered: each belongs to a side button that is
    still `disabled`, because each needs an editor of its own and there is no
    update endpoint to save it to. Keeping it makes those passes a UI change
    rather than a UI change plus another round trip.
    """

    def test_the_whole_note_is_kept(self):
        self.assertIn("const [note, setNote] = useState(null);", PAGE_CODE)
        self.assertIn("setNote(loaded);", PAGE_CODE)

    def test_it_is_cleared_on_every_open(self):
        """Or the next note opens holding the last one's photos."""
        self.assertIn("setNote(null);", PAGE_CODE)

    def test_link_and_tags_are_still_disabled(self):
        """Path has a picker now; these two have the data and no editor for
        it, which is not the same as being ready."""
        mapped = PAGE_CODE[PAGE_CODE.index("METADATA_FIELDS.map"):]

        self.assertIn("disabled", mapped[:mapped.index("))}")])


class SaveNotWiredTests(unittest.TestCase):
    def test_the_tick_still_only_closes(self):
        """This round is the read. There is no update endpoint, so ✓ does what
        it did before — closes — and this is what will fail when someone wires
        a save without also revisiting the docs that say it is not wired."""
        tick = PAGE_CODE[PAGE_CODE.index("fab commit"):]
        tick = tick[:tick.index("</button>")]

        self.assertIn("onClick={closeAddNote}", tick)

    def test_the_page_sends_nothing(self):
        """No POST, PUT or PATCH anywhere on the page yet."""
        for verb in ("apiPost", "apiPut", "apiPatch", "saveNote"):
            with self.subTest(verb=verb):
                self.assertNotIn(verb, PAGE_CODE)


if __name__ == "__main__":
    unittest.main()
