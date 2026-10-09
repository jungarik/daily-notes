"""The Add-note page's path wheel: its geometry, its roster, and its colour.

The geometry is the part worth real tests. `wheelItem` is the circle's own
equation — one value `t = √(1 − (dy/r)²)` driving offset, scale and opacity —
and the properties that matter are easy to break by "simplifying" it into a
linear ramp: the falloff must be *circular* (shallow near the centre, steep at
the rim), it must reach exactly 0 at the rim and stay there beyond it, and it
must be symmetric. Those run under node against the real module.

The page has two wheels — root folder and the sub-folder under it — each with
its own endpoint. What is pinned here is that both exist, are owner-scoped and
filtered in SQL, the root roster reports the default destination, and the one
thing nothing else protects against: a route order that makes them unreachable.
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
WEBAPP = ROOT / "browser" / "webapp" / "src"
FORMAT_JS = WEBAPP / "lib" / "format.js"
SECTION = ROOT / "api" / "addnote"
ENDPOINTS = (SECTION / "endpoints.py").read_text(encoding="utf-8")
DB_SOURCE = (SECTION / "db.py").read_text(encoding="utf-8")
WHEEL = (WEBAPP / "components" / "PathWheel.jsx").read_text(encoding="utf-8")
PAGE = (WEBAPP / "components" / "AddNote.jsx").read_text(encoding="utf-8")
CSS = (WEBAPP / "styles.css").read_text(encoding="utf-8")

SCRIPT = """
import { wheelItem, wheelOffset, wheelIndexAt, WHEEL_ITEM_HEIGHT, WHEEL_HEIGHT } from %s;
const [fn, args] = JSON.parse(process.argv[2]);
const sizes = () => ({ item: WHEEL_ITEM_HEIGHT, wheel: WHEEL_HEIGHT });
const call = { wheelItem, wheelOffset, wheelIndexAt, sizes }[fn];
console.log(JSON.stringify(call(...args)));
"""


def _js(fn, *args):
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "wheel.mjs"
        script.write_text(SCRIPT % json.dumps(FORMAT_JS.as_posix()), encoding="utf-8")
        out = subprocess.run(
            ["node", str(script), json.dumps([fn, list(args)])],
            capture_output=True, text=True, check=True)

    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node is not available")
class WheelGeometryTests(unittest.TestCase):
    def test_the_centre_item_is_whole(self):
        """Full opacity, full scale, and the furthest out along the arc."""
        item = _js("wheelItem", 0, 120, 26)

        self.assertAlmostEqual(1.0, item["opacity"])
        self.assertAlmostEqual(1.0, item["scale"])
        self.assertAlmostEqual(26.0, item["x"])

    def test_an_item_at_the_rim_is_invisible_and_flush(self):
        """`t` reaches exactly 0 there — the fade ends where the circle does,
        with no clipped half-visible row."""
        item = _js("wheelItem", 120, 120, 26)

        self.assertEqual(0, item["opacity"])
        self.assertEqual(0, item["x"])

    def test_beyond_the_rim_stays_at_zero(self):
        """`√` of a negative is NaN, which renders as a blank style and an
        item that never disappears. The clamp is the whole reason `t` is
        computed with a guard."""
        for dy in (121, 400, -400):
            with self.subTest(dy=dy):
                item = _js("wheelItem", dy, 120, 26)

                self.assertEqual(0, item["opacity"])
                self.assertEqual(0, item["x"])

    def test_the_falloff_is_circular_not_linear(self):
        """The property that makes it a wheel. Half way to the rim a linear
        ramp would be at .5; a circle is at √(1−.25) ≈ .87 — it holds its
        brightness near the centre and dives at the edge."""
        half = _js("wheelItem", 60, 120, 26)["opacity"]

        self.assertGreater(half, 0.8)
        self.assertAlmostEqual(0.866, half, places=2)

    def test_the_falloff_steepens_toward_the_rim(self):
        """Stated as a property rather than a number: each equal step costs
        more opacity than the one before it."""
        steps = [_js("wheelItem", dy, 120, 26)["opacity"]
                 for dy in (0, 30, 60, 90, 120)]
        drops = [steps[i] - steps[i + 1] for i in range(len(steps) - 1)]

        self.assertEqual(drops, sorted(drops))

    def test_it_is_symmetric(self):
        """An item above the centre and its mirror below must look identical,
        or the wheel leans."""
        above = _js("wheelItem", -45, 120, 26)
        below = _js("wheelItem", 45, 120, 26)

        self.assertEqual(above, below)

    def test_scale_never_collapses(self):
        """A floor of .78: an item scaled to nothing is a gap in the drum
        while still taking its row's height."""
        self.assertGreaterEqual(_js("wheelItem", 119, 120, 26)["scale"], 0.78)

    def test_the_reach_is_independent_of_the_radius(self):
        """Why they are two parameters: at `reach = radius` the centre item
        would shift 120px, off the side of a phone."""
        self.assertAlmostEqual(26.0, _js("wheelItem", 0, 120, 26)["x"])
        self.assertAlmostEqual(8.0, _js("wheelItem", 0, 120, 8)["x"])


@unittest.skipUnless(shutil.which("node"), "node is not available")
class WheelScrollTests(unittest.TestCase):
    def test_an_unscrolled_wheel_centres_its_first_item(self):
        """The list is padded by half its height, so index 0 can reach the
        middle — its offset at `scrollTop` 0 is half an item, not half a
        wheel."""
        self.assertEqual(20, _js("wheelOffset", 0, 0, 40, 240))

    def test_scrolling_moves_an_item_toward_the_centre(self):
        """Offset shrinks to 0 as its own row is scrolled to."""
        self.assertEqual(0, _js("wheelOffset", 3, 140, 40, 240))

    def test_the_centred_index_rounds_to_the_nearest_row(self):
        """A snap lands on a row, but a flick read mid-animation must not
        report a fractional index."""
        self.assertEqual(3, _js("wheelIndexAt", 125, 40))
        self.assertEqual(3, _js("wheelIndexAt", 135, 40))

    def test_a_negative_scroll_is_the_first_item(self):
        """iOS rubber-banding reports negative scrollTop."""
        self.assertEqual(0, _js("wheelIndexAt", -60, 40))


@unittest.skipUnless(shutil.which("node"), "node is not available")
class RowPitchTests(unittest.TestCase):
    """The pill's height lives in CSS, the row pitch in JS. They have to add
    up, and nothing at runtime notices if they stop: the wheel would simply
    drift out of step with its own scroll positions.
    """

    def test_the_css_pill_and_margins_make_the_js_row_pitch(self):
        start = CSS.index("  .path-wheel-opt {")
        rule = CSS[start:CSS.index("}", start)]
        height = int(re.search(r"height: (\d+)px", rule).group(1))
        margin = int(re.search(r"margin: (\d+)px 0", rule).group(1))

        self.assertEqual(_js("sizes")["item"], height + margin * 2)

    def test_the_wheel_runs_one_row_longer_than_it_reads(self):
        """Five readable rows needs six rows of run. The track's mask fades
        40px at each end, so the outermost row on either side is mid-dissolve
        — sizing the box to exactly the rows you want legible leaves the last
        one permanently half-faded, which is what a 5-row box did."""
        sizes = _js("sizes")
        start = CSS.index("  .path-wheel-track {")
        rule = CSS[start:CSS.index("}", start)]
        fade = int(re.search(r"#000 (\d+)px", rule).group(1))

        self.assertEqual(56, sizes["item"])
        self.assertEqual(6, sizes["wheel"] / sizes["item"])
        # The fade at each end has to stay inside one row, or it eats into the
        # second row in and the count is wrong again.
        self.assertLess(fade, sizes["item"])

    def test_the_rows_cannot_collapse_their_margins(self):
        """Adjacent block siblings merge their vertical margins — 6px + 6px
        would become 6px and every row would sit 50px apart while the maths
        assumed 56. A flex column is what prevents it."""
        start = CSS.index("  .path-wheel-track {")
        rule = CSS[start:CSS.index("}", start)]

        self.assertIn("display: flex", rule)
        self.assertIn("flex-direction: column", rule)
        self.assertIn("  .path-wheel-track > * { flex: none; }", CSS)

    def test_the_row_height_is_not_set_inline(self):
        """It would need an `!important` in the stylesheet to win it back."""
        self.assertNotIn("height: WHEEL_ITEM_HEIGHT,", WHEEL)


class LabelClipTests(unittest.TestCase):
    """A long path must not reach the pill's right edge, and must lose its
    *stem* rather than its leaf — the leaf is what tells two folders under one
    root apart. Done in CSS so it follows the pill's real width, where the
    character cap this replaced could only guess at it.
    """

    def _label_rule(self) -> str:
        start = CSS.index("  .path-wheel-label {")

        return CSS[start:CSS.index("}", start)]

    def test_the_overflow_is_moved_to_the_left(self):
        """`direction: rtl` is the only thing that puts the ellipsis at the
        start of a line."""
        rule = self._label_rule()

        self.assertIn("direction: rtl", rule)
        self.assertIn("text-overflow: ellipsis", rule)
        self.assertIn("white-space: nowrap", rule)

    def test_the_text_still_reads_left_to_right(self):
        """Inside an rtl box the `/` characters are neutral and migrate.
        `<bdi>` isolates the run so "Projects/api" stays itself."""
        self.assertIn("<bdi>{item}</bdi>", WHEEL)

    def test_the_label_can_actually_shrink(self):
        """`min-width: 0` — a flex child's default `min-width: auto` is its
        content, so the pill would grow instead of the text clipping."""
        self.assertIn("min-width: 0", self._label_rule())

    def test_the_pill_clips_what_escapes(self):
        start = CSS.index("  .path-wheel-opt {")
        rule = CSS[start:CSS.index("}", start)]

        self.assertIn("overflow: hidden", rule)

    def test_the_character_cap_is_gone(self):
        """A guess at pixel width, in two places, now that CSS does it."""
        self.assertNotIn("ellipsisPath", (WEBAPP / "lib" / "format.js")
                         .read_text(encoding="utf-8"))
        self.assertNotIn("ellipsisPath", WHEEL)


class RosterEndpointTests(unittest.TestCase):
    def test_the_rosters_are_declared_before_the_note_route(self):
        """FastAPI matches in declaration order. With `/{note_id}` first,
        `GET /api/addnote/roots` is answered 422 by the note handler — a
        broken feature with a correct endpoint behind it, which is exactly how
        `DELETE /api/contextmenu/notes/{id}` once shipped dead."""
        note_route = ENDPOINTS.index('@router.get("/{note_id}"')

        self.assertLess(ENDPOINTS.index('@router.get("/roots"'), note_route)
        self.assertLess(ENDPOINTS.index('@router.get("/children"'), note_route)

    def test_the_old_all_paths_roster_is_gone(self):
        """One request that shipped every path is what the two wheels
        replaced."""
        self.assertNotIn('@router.get("/paths"', ENDPOINTS)
        self.assertNotIn("def list_paths", DB_SOURCE)

    def test_the_section_owns_its_reads(self):
        """Duplicated from the contextmenu section rather than imported, so
        the editor's picker cannot break because the ⋮ menu's changed."""
        self.assertIn("def list_children(user_id: int, root: str) -> list[str]:", DB_SOURCE)
        self.assertNotIn("api.contextmenu", ENDPOINTS)

    def test_the_children_are_owner_scoped(self):
        self.assertIn("WHERE user_id = %s AND split_part(path, '/', 1) = %s", DB_SOURCE)

    def test_the_children_are_filtered_in_sql_not_in_python(self):
        """Choosing a root should read that root's notes, not the vault. And
        the root is matched as a whole segment: `LIKE 'Projects%'` would also
        catch `Projects2/x`."""
        self.assertIn("split_part(path, '/', 2)", DB_SOURCE)
        statement = DB_SOURCE.split("def list_children", 1)[1].split('"""', 3)[3]

        self.assertNotIn("LIKE", statement)

    def test_the_default_root_comes_from_config_not_from_position(self):
        """Reading the roster's first entry would work until the day the
        order and the default disagree, and then file notes somewhere else
        silently."""
        helper_source = (SECTION / "helper.py").read_text(encoding="utf-8")

        self.assertIn("config.DEFAULT_ROOT_FOLDER_KEY", helper_source)
        self.assertIn("default_root=helper.default_root(locale)", ENDPOINTS)

    def test_the_default_is_part_of_the_root_payload(self):
        """The page shows where an unpicked note will go, rather than an empty
        control that files it somewhere anyway."""
        schemas = (SECTION / "schemas.py").read_text(encoding="utf-8")

        self.assertIn("default_root", schemas)
        self.assertIn("class ChildrenPayload", schemas)


class ButtonStateTests(unittest.TestCase):
    def test_a_set_folder_lights_the_ring_and_the_glyph_only(self):
        """Not the fill. `--commit` as a *fill* is the app's one
        affirmative-action colour (Send, Confirm, the tick, the plus); a filled
        blue circle here would read as a button that does something rather than
        a field holding a value."""
        start = CSS.index("  .addnote-side .fab.set {")
        rule = CSS[start:CSS.index("}", start)]

        self.assertIn("color: var(--commit)", rule)
        self.assertIn("border-color: var(--commit)", rule)
        self.assertNotIn("background", rule)

    def test_the_glyph_inherits_that_colour(self):
        """The icons stroke `currentColor`, which is why the ring rule is
        enough — there is no second rule for the svg."""
        self.assertIn('stroke="currentColor"', PAGE)

    def test_a_button_is_lit_only_by_an_actual_choice(self):
        """`path` is "" until the user picks or the note arrives with one. The
        default destination does not light it: nobody chose."""
        self.assertIn('className={"fab" + (chosen ? " set" : "")}', PAGE)
        self.assertIn('const [path, setPath] = useState("");', PAGE)

    def test_the_two_buttons_are_views_of_one_saved_path(self):
        """The root is the first segment, the sub-folder the second; the save
        still sends the single `path` string, so the backend is unchanged."""
        self.assertIn('const [root, child = ""] = path.split("/");', PAGE)
        self.assertIn("const body = { text: text.trim(), path, tags: [] };", PAGE)

    def test_the_sub_folder_needs_a_root(self):
        self.assertIn("disabled={!isRoot && !root}", PAGE)

    def test_changing_the_root_clears_the_sub_folder(self):
        """A stale "Projects/api" must not survive a move to Areas — and
        re-picking the same root must not wipe the sub-folder."""
        self.assertIn("setPath((current) => (picked === root ? current : picked));", PAGE)

    def test_picking_a_sub_folder_appends_it_to_the_root(self):
        self.assertIn('setPath(root + "/" + picked)', PAGE)

    def test_only_the_sub_folder_wheel_accepts_a_new_name(self):
        """The server rejects an unknown root, so typing one would only end in
        a 422."""
        sub = PAGE[PAGE.index("load={() => listAddNoteChildren(root)}"):]

        self.assertIn("allowNew", sub.split("/>", 1)[0])
        self.assertNotIn("allowNew", PAGE.split("load={() => listAddNoteChildren(root)}")[0])

    def test_a_typed_slash_is_dropped(self):
        """A name with a slash would be a second level hiding in the first."""
        self.assertIn(r'.replace(/[\\/]/g, "")', WHEEL)

    def test_only_one_wheel_is_open_at_a_time(self):
        self.assertIn('const [openWheel, setOpenWheel] = useState("");', PAGE)
        self.assertNotIn("pathOpen", PAGE)

    def test_the_tags_button_is_still_disabled(self):
        branch = PAGE[PAGE.index('meta.field === "tags"'):]

        self.assertIn("disabled", branch.split("return (", 2)[1])

    def test_the_link_button_is_gone(self):
        self.assertNotIn('"Link to another note"', PAGE)

    def test_the_label_says_which_folder(self):
        """A circle that has changed colour does not say what it holds; the
        accessible name and the tooltip do."""
        self.assertIn('aria-label={chosen ? meta.label + ": " + chosen : meta.label}', PAGE)


class WheelStructureTests(unittest.TestCase):
    def test_the_wheel_is_anchored_to_the_button(self):
        """Positioned by the control it belongs to — `right: 100%` on the
        wrapper is "just left of the circle", which stays true wherever the
        column ends up."""
        self.assertIn("  .path-anchor { position: relative;", CSS)
        start = CSS.index("  .path-wheel {")
        rule = CSS[start:CSS.index("}", start)]

        self.assertIn("right: 100%", rule)
        self.assertIn("top: 50%", rule)

    def test_there_is_no_panel(self):
        """A container would be a second floating object competing with the
        bar the wheel hangs off, over a page that is already glass over the
        note's text. The rows are the whole control."""
        start = CSS.index("  .path-wheel {")
        rule = CSS[start:CSS.index("}", start)]

        for property_name in ("background", "backdrop-filter", "border", "box-shadow"):
            with self.subTest(property=property_name):
                self.assertNotIn(property_name, rule)

    def test_a_row_sits_above_the_page_without_being_glass(self):
        """The elevated surface the sheets use, a hairline so the note's text
        behind it does not bleed through the edge, and a lift. No blur: a row
        is not a floating bar, and the panel-as-glass version is the one that
        looked wrong."""
        start = CSS.index("  .path-wheel-opt {")
        rule = CSS[start:CSS.index("}", start)]

        self.assertIn("background: var(--bg-elev)", rule)
        self.assertIn("border: 1px solid rgba(255,255,255,.12)", rule)
        self.assertIn("box-shadow", rule)
        self.assertNotIn("backdrop-filter", rule)

    def test_a_row_is_as_wide_as_its_name(self):
        """What makes the column read as a list of folders rather than a stack
        of bars — and what "the whole option should be visible" asks for. The
        cap plus the label's left-side ellipsis handle the long ones."""
        start = CSS.index("  .path-wheel-opt {")
        rule = CSS[start:CSS.index("}", start)]
        start = CSS.index("  .path-wheel-track {")
        track = CSS[start:CSS.index("}", start)]

        self.assertIn("width: auto", rule)
        self.assertIn("max-width: 100%", rule)
        self.assertIn("align-items: flex-end", track)

    def test_the_arc_has_room_inside_the_scrollport(self):
        """The frame that was cutting the rows. `overflow-y: auto` computes
        `overflow-x: auto` too, so the leftward bow was clipped by the scroll
        box's own left edge — the padding is the bow's room, and it has to
        exceed `WHEEL_REACH`."""
        start = CSS.index("  .path-wheel-track {")
        track = CSS[start:CSS.index("}", start)]
        padding = int(re.search(r"padding-left: (\d+)px", track).group(1))

        self.assertGreater(padding, 26)
        self.assertIn("box-sizing: border-box", track)

    def test_each_row_carries_its_folders_colour(self):
        """`lib/format.pathColor` is the map's language for which folder a
        thing is in; reusing it here means no new palette, and a column of
        near-identical names gains something to recognise."""
        self.assertIn("pathColor(colorPrefix + item)", WHEEL)
        self.assertIn("  .path-wheel-dot {", CSS)

    def test_the_dot_cannot_be_squeezed_away(self):
        start = CSS.index("  .path-wheel-dot {")
        rule = CSS[start:CSS.index("}", start)]

        self.assertIn("flex: none", rule)

    def test_the_chosen_folder_is_filled_blue(self):
        """A deliberate exception to "`--commit` as a fill means an
        affirmative action": in a list where every row is a candidate, the one
        that is already the answer has to be unmissable, and a hairline would
        be lost among rows that have borders of their own."""
        start = CSS.index("  .path-wheel-opt.on {")
        rule = CSS[start:CSS.index("}", start)]

        self.assertIn("background: var(--commit)", rule)
        self.assertIn("color: #fff", rule)

    def test_the_filter_is_the_one_full_width_row(self):
        """A text field that grew as you type would move its own caret."""
        start = CSS.index("  .path-wheel-opt.filter {")
        rule = CSS[start:CSS.index("}", start)]

        self.assertIn("align-self: stretch", rule)

    def test_the_options_snap(self):
        """So a flick settles on an option rather than between two."""
        self.assertIn("scroll-snap-type: y mandatory", CSS)
        self.assertIn("scroll-snap-align: center", CSS)

    def test_the_pills_scale_away_from_the_button(self):
        """`transform-origin: 100% 50%`: they are anchored to the button's
        side, so scaling must not drift them sideways."""
        start = CSS.index("  .path-wheel-opt {")
        rule = CSS[start:CSS.index("}", start)]

        self.assertIn("transform-origin: 100% 50%", rule)

    def test_the_fade_works_two_ways(self):
        """Per-row opacity *and* a mask on the track, doing different jobs:
        the first follows a row along the arc (the wheel turning away), the
        second is tied to the visible boundary, so a row that happens to sit
        at the edge dissolves into it whatever the geometry says."""
        self.assertIn("opacity,", WHEEL)
        start = CSS.index("  .path-wheel-track {")
        rule = CSS[start:CSS.index("}", start)]

        self.assertIn("mask-image: linear-gradient(to bottom", rule)

    def test_the_mask_fades_both_ends(self):
        """The top was the broken one, but masking only there would leave the
        two edges dissolving by different mechanisms and not looking like
        siblings."""
        start = CSS.index("  .path-wheel-track {")
        rule = CSS[start:CSS.index("}", start)]
        mask = rule[rule.index("mask-image: linear-gradient(to bottom"):]

        self.assertIn("transparent 0", mask)
        self.assertIn("transparent 100%", mask)
        self.assertIn("calc(100% - 40px)", mask)

    def test_the_mask_is_prefixed_for_webkit(self):
        """Telegram's webview is WebKit, where the unprefixed property is not
        enough — and a missing mask is exactly the bug this fixes."""
        start = CSS.index("  .path-wheel-track {")
        rule = CSS[start:CSS.index("}", start)]

        self.assertIn("-webkit-mask-image:", rule)

    def test_a_faded_item_cannot_be_tapped(self):
        """It is invisible; keeping its hit zone makes the wheel's dead space
        tappable."""
        self.assertIn('pointerEvents: opacity < 0.15 ? "none" : "auto"', WHEEL)

    def test_the_wheel_opens_on_the_notes_own_path(self):
        """Or on the default destination when it has none, so it starts where
        the note would actually go."""
        self.assertIn("options.indexOf(value || defaultPath)", WHEEL)

    def test_the_filter_is_the_first_row(self):
        """Not a header above the list: it wears the same pill as every
        option, so "type something new" is an option rather than a mode."""
        self.assertIn('className="path-wheel-opt filter"', WHEEL)
        self.assertIn("  .path-wheel-opt.filter {", CSS)
        self.assertLess(WHEEL.index("path-wheel-opt filter"),
                        WHEEL.index("options.map("))

    def test_the_filter_fades_like_any_other_row(self):
        """It had an opacity floor so it could not be missed. But as the
        *topmost* row that made the top of the wheel the one edge where
        nothing ever disappeared — which reads as a broken fade, not as a
        helpful control. It takes `row(0)` unmodified now."""
        self.assertIn('className="path-wheel-opt filter" style={row(0)}', WHEEL)
        self.assertNotIn("Math.max(", WHEEL)
        self.assertNotIn("filterStyle", WHEEL)

    def test_a_typed_path_is_an_ordinary_option_row(self):
        """Selecting it is how you use it, so there is no separate "create"
        control to explain."""
        self.assertIn("const isNew = allowNew && typed !== \"\" && !items.includes(typed);", WHEEL)
        self.assertIn("return isNew ? [typed, ...matching] : matching;", WHEEL)
        self.assertIn('e.key === "Enter" && typed', WHEEL)

    def test_the_options_are_offset_by_the_filters_row(self):
        """Row 0 is the filter, so option `i` is row `i + 1` — and the scroll
        that centres the current path has to account for it."""
        self.assertIn("style={row(index + 1)}", WHEEL)
        self.assertIn("(found < 0 ? 0 : found + 1) * WHEEL_ITEM_HEIGHT", WHEEL)

    def test_it_dismisses_on_an_outside_tap(self):
        """Deferred, so the opening tap does not close it — the same trick as
        the ⋮ menu's."""
        self.assertIn("setTimeout(() => document.addEventListener", WHEEL)

    def test_picking_closes_the_wheel(self):
        self.assertIn('setOpenWheel("");', PAGE)

    def test_the_choice_is_cleared_with_the_page(self):
        """Nothing saves it yet, so it must not survive into the next note."""
        self.assertIn('setPath("");', PAGE)


if __name__ == "__main__":
    unittest.main()
