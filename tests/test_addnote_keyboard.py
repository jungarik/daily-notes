"""The Add-note page's keyboard handling.

Two things here are easy to get wrong and impossible to see in a passing render:

* **`keyboardInset`** decides how far the floating bar lifts. Ignore
  `offsetTop` and the bar drifts as iOS scrolls the visual viewport under the
  keyboard; forget the `Math.max` and a viewport briefly *taller* than the
  window pushes the bar off the bottom of the screen.
* **The focus path.** iOS and Telegram's webview raise the keyboard only for a
  `focus()` made inside a user gesture. That forces two structural choices —
  the overlay is never unmounted or `display: none` (neither leaves a focusable
  element), and `openAddNote` focuses before it patches state. Both look like
  stylistic quirks and would be "tidied away" by the next reader, so they are
  pinned here.

The maths runs under node against the real module; the structure is read from
source, because what matters is which construct is used, not what it renders to.
"""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
FORMAT_JS = ROOT / "browser" / "webapp" / "src" / "lib" / "format.js"
ADDNOTE = ROOT / "browser" / "webapp" / "src" / "components" / "AddNote.jsx"
CONTEXT = ROOT / "browser" / "webapp" / "src" / "store" / "AppContext.jsx"
CSS = ROOT / "browser" / "webapp" / "src" / "styles.css"

SCRIPT = """
import { visibleViewport } from %s;
const cases = JSON.parse(process.argv[2]);
console.log(JSON.stringify(cases.map(visibleViewport)));
"""


def _boxes(cases):
    script = ROOT / "tests" / ".visible_viewport.mjs"
    script.write_text(SCRIPT % json.dumps(FORMAT_JS.as_posix()), encoding="utf-8")
    try:
        out = subprocess.run(["node", str(script), json.dumps(cases)],
                             capture_output=True, text=True, check=True)
    finally:
        script.unlink(missing_ok=True)

    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node is not available")
class VisibleViewportTests(unittest.TestCase):
    """What the overlay is sized to while the keyboard is up.

    The bug this replaced: the old helper derived a keyboard height by
    subtracting `visualViewport.height` from `window.innerHeight`. iOS does not
    shrink `innerHeight` for the keyboard and Telegram's webview resizes its
    container on its own, so the two disagreed by nearly a full page — the bar
    lifted by that and left the top of the screen. Reading only the visual
    viewport removes the second number, and with it the whole class of bug.
    """

    def test_it_reports_the_viewport_as_a_box(self):
        self.assertEqual([{"top": 0, "height": 800}],
                         _boxes([{"height": 800, "offsetTop": 0}]))

    def test_an_open_keyboard_shortens_the_box(self):
        """Nothing is subtracted from anything: the height *is* the visible
        height, so the overlay ends where the keyboard begins."""
        self.assertEqual([{"top": 0, "height": 500}],
                         _boxes([{"height": 500, "offsetTop": 0}]))

    def test_a_scrolled_visual_viewport_moves_the_box_down(self):
        """iOS scrolls the visual viewport when the keyboard opens; `offsetTop`
        is where it now starts, so the overlay follows rather than drifting."""
        self.assertEqual([{"top": 60, "height": 400}],
                         _boxes([{"height": 400, "offsetTop": 60}]))

    def test_a_viewport_without_offsettop_is_treated_as_unscrolled(self):
        self.assertEqual([{"top": 0, "height": 500}], _boxes([{"height": 500}]))

    def test_a_missing_visual_viewport_gives_no_box(self):
        """Older webviews have none. Null tells the caller to leave the overlay
        full-screen, exactly as it behaved before any of this existed."""
        self.assertEqual([None, None], _boxes([None, 0]))

    def test_it_reads_nothing_but_the_viewport(self):
        """The guard against the bug returning: a second source of truth is
        what broke this, so the helper takes one argument and no globals."""
        source = FORMAT_JS.read_text(encoding="utf-8")
        body = source.split("export function visibleViewport", 1)[1].split("\n}", 1)[0]

        self.assertNotIn("innerHeight", body)
        self.assertNotIn("window", body)
        self.assertNotIn("document", body)


class FocusPathTests(unittest.TestCase):
    """Why the overlay is always mounted, and why focus precedes the patch."""

    def setUp(self):
        self.addnote = ADDNOTE.read_text(encoding="utf-8")
        self.context = CONTEXT.read_text(encoding="utf-8")
        self.css = CSS.read_text(encoding="utf-8")

    def test_the_overlay_is_never_unmounted_while_closed(self):
        """`if (!open) return null` is the obvious tidy-up and it breaks the
        keyboard: there is then no textarea to focus during the tap."""
        self.assertNotRegex(self.addnote, r"return null")

    def test_the_overlay_is_hidden_with_opacity_not_display(self):
        """`display: none` and `visibility: hidden` both make a field
        unfocusable; opacity does not."""
        block = self.css.split(".addnote {", 1)[1].split("}", 1)[0]

        self.assertIn("opacity: 0", block)
        self.assertNotIn("display: none", block)
        self.assertNotIn("visibility: hidden", block)

    def test_the_hidden_overlay_does_not_swallow_taps(self):
        """It covers the whole screen at z-index 60 even when invisible."""
        block = self.css.split(".addnote {", 1)[1].split("}", 1)[0]

        self.assertIn("pointer-events: none", block)

    def test_opening_focuses_before_it_patches_state(self):
        """The gesture is alive only until the handler returns, and `patch` is
        async — focusing after the re-render gets a caret and no keyboard."""
        body = self.context.split("const openAddNote", 1)[1].split("const closeAddNote", 1)[0]
        focus_at = body.index(".focus()")
        patch_at = body.index("patch(")

        self.assertLess(focus_at, patch_at)

    def test_the_input_ref_is_shared_through_the_store(self):
        """The button that opens the page is in Header, the field is in
        AddNote; they meet at the ref rather than through a DOM query."""
        self.assertIn("addNoteInputRef", self.context)
        self.assertIn("addNoteInputRef", self.addnote)

    def test_the_closed_field_is_out_of_the_tab_order(self):
        """Still in the DOM, so it must not be reachable by keyboard."""
        self.assertIn("tabIndex={open ? 0 : -1}", self.addnote)


class BarTests(unittest.TestCase):
    def setUp(self):
        self.addnote = ADDNOTE.read_text(encoding="utf-8")
        self.css = CSS.read_text(encoding="utf-8")

    def test_every_circle_on_the_page_reuses_the_dock_glass(self):
        """None of these can drift from the dock in size, border or shadow.

        Counted as *declarations*, not rendered buttons: ✕, ✓ and the view
        toggle are written out, while the metadata fields share one `.fab`
        inside a `.map`, so four literals render six circles. Matched on the
        class prefix because the tick adds a `commit` modifier.

        The check that matters is the converse — no button anywhere on the page
        is a circle *without* `.fab` — so it is asserted directly below.
        """
        self.assertEqual(4, len(re.findall(r'className="fab\b', self.addnote)))

    def test_no_button_outside_the_info_corner_skips_fab(self):
        """The one exception is the info button, which is deliberately bare."""
        classes = re.findall(r'className=\{?"([\w -]+)"', self.addnote)
        buttons = [name for name in classes
                   if "fab" in name or "addnote-info-btn" in name]

        # Seven: ✕, ✓, AI, the path circle, the favourite star, the shared
        # disabled circle, and the bare info button.
        self.assertEqual(7, len(buttons))
        self.assertEqual(1, sum("addnote-info-btn" in name for name in buttons))

    def test_only_the_tick_is_the_commit_colour(self):
        """A discard should not compete with the commit for attention."""
        self.assertEqual(1, self.addnote.count('className="fab commit"'))

    def test_the_capture_pill_reuses_the_docks_capsule(self):
        """`.tabbar` is the dock's own pill class, so the two capsules cannot
        drift apart in blur, border or radius."""
        self.assertIn('className="tabbar"', self.addnote)

    def test_the_pill_offers_the_three_capture_kinds(self):
        """The same three the bot accepts, plus the one bit of metadata worth
        setting while the thought is fresh."""
        self.assertEqual(["photo", "voice", "reminder"],
                         re.findall(r'kind: "(\w+)"', self.addnote))

    def test_every_capture_button_is_disabled(self):
        """There is no note-create endpoint yet, so none of these can do
        anything. `disabled` is what makes that legible rather than looking
        like a button that swallowed the tap."""
        pill = self.addnote.split('className="tabbar"', 1)[1].split("</nav>", 1)[0]

        self.assertEqual(1, pill.count("<button"))
        self.assertEqual(1, pill.count("disabled"))

    def test_the_icon_only_buttons_carry_accessible_names(self):
        """Bare glyphs are unreadable to a screen reader without one.

        Counted inside the CAPTURE_KINDS array rather than across the file:
        VIEW_MODES declares labels of its own, so a whole-file count reads 5
        and fails on correct code."""
        kinds = self.addnote.split("const CAPTURE_KINDS = [", 1)[1].split("\n];", 1)[0]

        self.assertIn("aria-label={capture.label}", self.addnote)
        self.assertEqual(3, len(re.findall(r'label: "[^"]+"', kinds)))

    def test_the_overlay_is_sized_to_the_visible_viewport(self):
        """This is what puts the bar above the keyboard. `bottom: auto` is not
        cosmetic — without it the CSS `inset: 0` pins the bottom edge to the
        screen and fights the explicit height."""
        self.assertIn("style={box ? { top: box.top, height: box.height, bottom: \"auto\" }",
                      self.addnote)

    def test_the_bar_does_no_keyboard_arithmetic_of_its_own(self):
        """It is a plain bottom offset in CSS now. An inline `bottom` computed
        from a measured inset is what put the bar off the top of the screen."""
        self.assertNotIn("${inset}", self.addnote)
        self.assertNotIn("innerHeight", self.addnote)

        block = self.css.split(".addnote-bar {", 1)[1].split("}", 1)[0]

        self.assertIn("bottom: calc(30px + env(safe-area-inset-bottom, 0px))", block)

    def test_the_text_clears_both_floating_bars(self):
        """Both bars float over the textarea, so without padding on those two
        sides the text slides under glass mid-sentence — 100px at the bottom
        for the circles, 74px at the right for the side capsule."""
        block = self.css.split("\n  .addnote-body {", 1)[1].split("}", 1)[0]
        padding = re.search(r"padding:(.*?);", block, re.S).group(1)

        self.assertIn("100px", padding)
        self.assertIn("74px", padding)


class SideBarTests(unittest.TestCase):
    def setUp(self):
        self.addnote = ADDNOTE.read_text(encoding="utf-8")
        self.css = CSS.read_text(encoding="utf-8")

    def test_the_column_is_circles_not_a_capsule(self):
        """Every control on this edge is the same `.fab` as the ✕ and ✓, in a
        plain flex column — no capsule grouping any of them."""
        self.assertNotIn("tabbar vertical", self.addnote)

        block = self.css.split(".addnote-side {", 1)[1].split("}", 1)[0]

        self.assertIn("flex-direction: column", block)

    def test_the_whole_column_is_centred_as_one_group(self):
        """The container carries the centring, not any single button, so the
        column stays balanced as fields are added or removed."""
        block = self.css.split(".addnote-side {", 1)[1].split("}", 1)[0]

        self.assertIn("top: 50%", block)
        self.assertIn("translateY(-50%)", block)

    def test_the_metadata_fields_are_path_subpath_and_tags(self):
        self.assertEqual(["path", "subpath", "tags", "favorite"],
                         re.findall(r'field: "(\w+)"', self.addnote))

    def test_only_tags_is_still_inert(self):
        """The root and sub-folder have wheels and somewhere to put the answer
        (the page's own `path`); tags has neither, and a live-looking button
        that swallows the tap reads as a bug where a dimmed one reads as
        not-yet. So the map has exactly one early-returned disabled button."""
        fields = self.addnote.split("const METADATA_FIELDS = [", 1)[1].split("\n];", 1)[0]
        mapped = self.addnote.split("{METADATA_FIELDS.map(", 1)[1].split("\n        })}", 1)[0]

        self.assertEqual(4, len(re.findall(r'label: "[^"]+"', fields)))
        self.assertEqual(1, len(re.findall(r"\n\s+disabled\n", mapped)))
        self.assertIn('meta.field === "tags"', mapped)

    def test_the_favourite_star_sits_directly_under_tags_in_the_group(self):
        """Same gap as the rest: one more circle in the existing group, not set
        apart the way the AI button is."""
        fields = re.findall(r'field: "(\w+)"', self.addnote)

        self.assertEqual("favorite", fields[fields.index("tags") + 1])
        self.assertEqual("favorite", fields[-1])

    def test_the_star_toggles_a_local_flag_and_saves_nothing(self):
        """A placeholder. It must not reach the request, or a later reader
        assumes the server stores it."""
        self.assertIn("const [favorite, setFavorite] = useState(false);", self.addnote)
        self.assertIn("onClick={() => setFavorite((on) => !on)}", self.addnote)
        self.assertIn("const body = { text: text.trim(), path, tags: [] };", self.addnote)
        self.assertNotIn("favorite", self.addnote.split("const body =", 1)[1].split(";", 1)[0])

    def test_the_star_resets_every_time_the_page_opens(self):
        effect = self.addnote.split("if (!open) return;", 1)[1].split("}, [open, note_id]);", 1)[0]

        self.assertIn("setFavorite(false);", effect)

    def test_the_star_fills_and_lights_when_on_and_says_so(self):
        """Filled star plus the ring-and-glyph lit state a chosen folder uses —
        never the blue fill that means 'this button commits' — and exposed to
        assistive tech as a pressed toggle."""
        star = self.addnote.split('meta.field === "favorite"', 1)[1].split("</button>", 1)[0]

        self.assertIn('className={"fab" + (favorite ? " set" : "")}', star)
        self.assertIn('fill={favorite ? "currentColor" : "none"}', star)
        self.assertIn("aria-pressed={favorite}", star)
        self.assertIn("aria-label={meta.label}", star)
        self.assertNotIn("disabled", star)
        self.assertIn("  .addnote-side .fab.set { color: var(--commit); border-color: var(--commit); }",
                      self.css)

    def test_the_reminder_button_stayed_in_the_bottom_pill(self):
        """It is metadata too, but it was left where it was rather than churn
        a bar that is already settled."""
        self.assertIn('kind: "reminder"', self.addnote)
        self.assertNotIn('field: "reminder"', self.addnote)

    def test_the_vertical_capsule_rule_is_gone_with_it(self):
        """Dead CSS for a class nothing renders reads as a live variant."""
        self.assertNotIn(".tabbar.vertical", self.css)

    def test_it_is_pinned_to_the_right_and_centred_on_the_screen(self):
        block = self.css.split(".addnote-side {", 1)[1].split("}", 1)[0]

        self.assertIn("right:", block)
        self.assertIn("top: 50%", block)
        self.assertIn("translateY(-50%)", block)

    def test_the_ai_button_leads_the_column_and_is_inert(self):
        """It acts *on* the note where the three below describe it, so it comes
        first and stands apart. Inert like the rest — there is nothing to act
        on until a note can be saved."""
        button = self.addnote.split('className="fab addnote-ai"', 1)[1].split(">", 1)[0]

        self.assertIn("disabled", button)
        self.assertLess(self.addnote.index("addnote-ai"),
                        self.addnote.index("METADATA_FIELDS.map"))

    def test_the_ai_button_is_set_apart_by_spacing_not_by_shape(self):
        """A second shape in a column of circles would read as a different kind
        of control rather than the same kind doing a different job."""
        self.assertIn("className=\"fab addnote-ai\"", self.addnote)

        block = self.css.split(".addnote-ai {", 1)[1].split("}", 1)[0]

        self.assertIn("margin-bottom", block)

    def test_the_markdown_mode_toggle_is_gone(self):
        """Removed with its glyphs and its state — a toggle left behind with no
        renderer to drive is a control that does nothing."""
        for leftover in ("EyeGlyph", "PencilGlyph", "setReading"):
            with self.subTest(leftover=leftover):
                self.assertNotIn(leftover, self.addnote)

    def test_the_column_is_smaller_than_the_dock(self):
        """15% off 54px, scoped to this column: `.fab` is shared, so an
        unscoped size change would shrink every circle in the app."""
        block = self.css.split(".addnote-side .fab {", 1)[1].split("}", 1)[0]

        self.assertIn("46px", block)

        dock = self.css.split("\n  .fab {", 1)[1].split("}", 1)[0]

        self.assertIn("54px", dock)


class InfoPanelTests(unittest.TestCase):
    """The `i` button and the frontmatter block it toggles above the text."""

    def setUp(self):
        self.addnote = ADDNOTE.read_text(encoding="utf-8")
        self.css = CSS.read_text(encoding="utf-8")

    def test_the_info_button_is_live(self):
        """Every other button on this page is disabled or acts; this one is the
        whole point, so it must not have been copied with the `disabled`."""
        button = self.addnote.split('aria-label="Note info"', 1)[1].split("</button>", 1)[0]

        self.assertNotIn("disabled", button)
        self.assertIn("setInfoOpen((open) => !open)", button)
        self.assertIn("aria-expanded={infoOpen}", button)

    def test_the_cheat_sheet_is_gone(self):
        """The `?` button and its Markdown panel were replaced, not kept."""
        self.assertFalse((ROOT / "browser" / "webapp" / "src" / "components"
                          / "MarkdownHelp.jsx").exists())
        self.assertNotIn("MarkdownHelp", self.addnote)
        self.assertNotIn("md-help", self.css)
        self.assertNotIn("addnote-help", self.css)

    def test_the_icon_is_an_i_in_a_circle(self):
        icon = self.addnote.split('aria-label="Note info"', 1)[1].split("</svg>", 1)[0]

        self.assertIn('<circle cx="12" cy="12" r="9" />', icon)
        self.assertIn('<path d="M12 11v5.5" />', icon)
        self.assertIn('<path d="M12 7.7h.01" />', icon)

    def test_the_block_sits_above_the_text_in_the_pages_flow(self):
        """In the flex column before the textarea, so opening it pushes the text
        down rather than covering the first lines."""
        self.assertLess(self.addnote.index('className="addnote-info"'),
                        self.addnote.index('className="addnote-body"'))

        block = self.css.split(".addnote-info {", 1)[1].split("}", 1)[0]

        self.assertNotIn("position: absolute", block)
        self.assertIn("flex: none", block)

    def test_it_is_separated_from_the_text_by_a_line(self):
        block = self.css.split(".addnote-info {", 1)[1].split("}", 1)[0]

        self.assertIn("border-bottom: 1px solid var(--border)", block)

    def test_it_clears_the_info_button(self):
        """The button reaches 48px in from the edge; the block's right padding
        is the same 74px the textarea uses, so its text never runs under it."""
        block = self.css.split(".addnote-info {", 1)[1].split("}", 1)[0]

        self.assertIn("74px", block)

    def test_the_text_does_not_pay_the_safe_area_twice(self):
        self.assertIn(".addnote-info + .addnote-body { padding-top: 12px; }", self.css)

    def test_it_shows_the_path_row_read_only(self):
        """One row for now, built from a list so backlinks can join it."""
        self.assertIn('{ key: "path", icon: <FolderGlyph />, value: path || defaultDestination, isDefault: !path }',
                      self.addnote)
        info = self.addnote.split('className="addnote-info"', 1)[1].split("<textarea", 1)[0]

        self.assertNotIn("<input", info)

    def test_the_path_row_is_labelled_by_the_folder_glyph_not_a_word(self):
        """The same folder the path button draws, from one component — so the
        two cannot drift apart."""
        self.assertIn("function FolderGlyph()", self.addnote)
        self.assertEqual(1, self.addnote.count("M3 6.5A1.5 1.5 0 0 1 4.5 5h4L11 7.5"))
        self.assertIn('className="addnote-info-icon">{row.icon}</span>', self.addnote)
        self.assertNotIn("addnote-info-key", self.addnote + self.css)

    def test_the_info_text_is_smaller_and_greyer_than_the_note(self):
        """It is metadata about the text, so it must read differently from it:
        13px against the textarea's 16px, and the muted grey rather than the
        text colour."""
        row = self.css.split(".addnote-info-row {", 1)[1].split("}", 1)[0]
        value = self.css.split(".addnote-info-value {", 1)[1].split("}", 1)[0]
        icon = self.css.split(".addnote-info-icon {", 1)[1].split("}", 1)[0]

        self.assertIn("font-size: 13px", row)
        self.assertIn("color: var(--text-muted)", value)
        self.assertIn("color: var(--text-muted)", icon)

    def test_nothing_chosen_shows_the_default_dimmed(self):
        self.assertIn(".addnote-info-value.is-default { color: var(--text-faint); }", self.css)
        self.assertIn('(row.isDefault ? " is-default" : "")', self.addnote)

    def test_the_default_root_is_read_only_when_it_is_needed(self):
        """Not on every open: only with the block showing and nothing chosen."""
        effect = self.addnote.split("if (!infoOpen || path || defaultDestination) return;", 1)[1] \
                             .split("}, [infoOpen, path, defaultDestination]);", 1)[0]

        self.assertIn("listAddNoteRoots()", effect)

    def test_it_reopens_closed_on_the_next_visit(self):
        """Per-visit, not a preference: a block left open would push the text
        down the next time the page is opened.

        Scoped to the on-open effect. Searching the whole file matches the
        toggle too, which is always there."""
        effect = self.addnote.split("if (!open) return;", 1)[1].split("}, [open]);", 1)[0]

        self.assertIn("setInfoOpen(false)", effect)

    def test_the_info_button_carries_no_glass_of_its_own(self):
        """The glyph is already a circled `i`. Any ring or blur around it would
        be a second circle drawn around the first."""
        block = self.css.split(".addnote-info-btn {", 1)[1].split("}", 1)[0]

        self.assertIn("border: none", block)
        self.assertIn("background: none", block)
        self.assertNotIn("backdrop-filter", block)

    def test_the_button_outranks_the_block_it_sits_over(self):
        block = self.css.split(".addnote-info-btn {", 1)[1].split("}", 1)[0]

        self.assertIn("z-index: 2", block)


class ClosedOverlayTests(unittest.TestCase):
    """A `pointer-events: auto` child stays tappable under a `none` parent.

    The overlay is always mounted and covers the whole screen at z-index 60, so
    any control inside it that claims `auto` unconditionally is live over the
    feed while the page is invisible — a tap landing where Done sits would fire
    Done on a page nobody can see. Every such rule must be scoped to `.show`.
    """

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8")

    def test_no_control_inside_the_overlay_claims_taps_unconditionally(self):
        offending = [
            line.strip()
            for line in self.css.splitlines()
            if "pointer-events: auto" in line
            and ".addnote" in line
            and ".addnote.show" not in line
        ]

        self.assertEqual([], offending)

    def test_both_bars_are_re_enabled_only_when_the_page_shows(self):
        self.assertIn(".addnote.show .addnote-bar > * { pointer-events: auto; }", self.css)
        self.assertIn(".addnote.show .addnote-side { pointer-events: auto; }", self.css)


if __name__ == "__main__":
    unittest.main()
