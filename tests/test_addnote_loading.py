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


class SaveTests(unittest.TestCase):
    """The ✓, wired.

    The decisions worth pinning are the ones that cost the user something when
    they go wrong: a double-tap that creates two notes, a failure that closes
    the page over the text it is failing to save, and an empty save the API can
    only answer with a 422 nobody can act on.
    """

    def test_the_verb_depends_on_whether_there_is_an_id(self):
        """Not one "upsert": a POST that silently updated, or a PUT that
        silently created, is an endpoint nobody can reason about from the call
        site."""
        self.assertIn("if (note_id == null) await createNote(body);", PAGE_CODE)
        self.assertIn("else await saveNote(note_id, body);", PAGE_CODE)

    def test_the_tick_saves_rather_than_closing(self):
        tick = PAGE_CODE[PAGE_CODE.index("fab commit"):]
        tick = tick[:tick.index("</button>")]

        self.assertIn("onClick={save}", tick)
        self.assertNotIn("onClick={closeAddNote}", tick)

    def test_a_second_tap_cannot_save_twice(self):
        """`disabled` is the visible half; the guard inside the handler is the
        one that holds, because a tap already dispatched before the re-render
        would otherwise run the whole sequence again."""
        tick = PAGE_CODE[PAGE_CODE.index("fab commit"):]
        tick = tick[:tick.index("</button>")]

        self.assertIn("disabled={!canSave}", tick)
        self.assertIn("if (!canSave) return;", PAGE_CODE)

    def test_an_empty_note_cannot_be_saved(self):
        """The API requires one character, so an empty save is a 422 the user
        cannot act on. A dimmed tick says "not yet" instead."""
        self.assertIn('const canSave = text.trim() !== "" && !saving;', PAGE_CODE)

    def test_the_tick_is_dimmed_while_saving(self):
        self.assertIn("  .addnote-bar .fab:disabled {", CSS)

    def test_tags_go_as_an_empty_list(self):
        """Their button is still disabled, so there is nothing to send."""
        self.assertIn("tags: [] }", PAGE_CODE)

    def test_an_unset_path_is_sent_empty_rather_than_guessed(self):
        """The API files it under the configured default root. A client that
        invented a folder name here would be the retired `defaultRoot`
        behaviour by another route."""
        self.assertIn("path, tags: []", PAGE_CODE)

    def test_a_failure_keeps_the_page_and_the_text(self):
        """Closing on a failure discards what the user wrote in order to tell
        them it was not saved."""
        body = PAGE_CODE[PAGE_CODE.index("const save = async"):]
        body = body[:body.index("closeAddNote()")]

        self.assertIn("catch (err)", body)
        self.assertIn("return;", body)
        self.assertNotIn("closeAddNote", body)

    def test_a_422_says_what_is_wrong(self):
        """The only failure the user can fix from here is the folder."""
        self.assertIn('String(err).includes("422")', PAGE_CODE)

    def test_the_vault_is_reloaded_after_a_save(self):
        """Feed, explorer, map and the header counts all derive from the boot
        fetch, so `reload` is the one path that means "the vault changed" —
        the same one the ⋮ menu's path change and delete take."""
        self.assertIn("closeAddNote();\n    reload();", PAGE_CODE)

    def test_the_save_state_resets_on_every_open(self):
        """Or the next note opens showing the last one's error."""
        self.assertIn('setSaveState("");', PAGE_CODE)

    def test_the_error_line_is_shared_with_the_failed_read(self):
        """Two messages, one place to look — and they cannot both apply: a
        note that failed to load has nothing to save."""
        self.assertIn('status === "failed" || (saveState && !saving)', PAGE_CODE)


if __name__ == "__main__":
    unittest.main()
