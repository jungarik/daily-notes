// Small pure formatting helpers shared across components.

export function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

// Compact dd/mm/yy for tight spots like the chat note card.
export function fmtDateShort(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${String(d.getFullYear()).slice(-2)}`;
}

// A stable colour for a note's path: every note filed in the same folder gets
// the same hue, so the map's dots and card borders group by folder at a glance.
export function pathColor(path, sat = 52, light = 58) {
  // A hash seed, never shown — so it needs no label, just stability.
  const key = String(path || "").trim();
  let h = 0;

  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;

  return "hsl(" + (h % 360) + "," + sat + "%," + light + "%)";
}

// A note's folder key for the filter (its path, or a bucket for unsorted notes).
// Which folder a note belongs to. Every note the vault views receive has a
// path — the API filters out the ones that do not — so there is nothing to
// fall back to.
export const notePathKey = (d) => (d && d.path) || "";

export const dateText = (d) => fmtDate(d && d.created_at);
export const tagsText = (d) => (d && d.tags && d.tags.length ? "🏷 " + d.tags.join(", ") : "");

// De-duplicated depth-1 neighbours (links + backlinks), for the card + preview.
export function linkedItems(detail) {
  const seen = new Set(), items = [];
  for (const it of [...((detail && detail.links) || []), ...((detail && detail.backlinks) || [])]) {
    if (seen.has(it.id)) continue;
    seen.add(it.id); items.push(it);
  }
  return items;
}

// The area actually visible, in layout-viewport coordinates — what is left of
// the page once the on-screen keyboard covers the bottom of it.
//
// This deliberately reads `visualViewport` and NOTHING else. The previous
// version subtracted it from `window.innerHeight` to derive a keyboard height,
// and `innerHeight` is the one number that cannot be trusted here: iOS does not
// shrink it for the keyboard, and Telegram's webview resizes its container
// independently, so the two disagreed and the difference — meant to be the
// keyboard — came out near the full page height. The bar lifted by that and
// left the screen.
//
// Returning the box instead of a height means the caller sizes the overlay to
// it, so "sit above the keyboard" becomes ordinary bottom-anchoring inside a
// shorter box rather than arithmetic that can be wrong.
//
// Null when the browser has no `visualViewport`: the caller then leaves the
// overlay full-screen, exactly as it behaved before any of this existed.
export function visibleViewport(viewport) {
  if (!viewport) return null;

  return { top: viewport.offsetTop || 0, height: viewport.height };
}

// --- the header's Inbox ring ------------------------------------------------

// How many segments the ring can show. The Inbox is a to-do pile, not a
// gauge: past a dozen the exact number stops being the point, and the ring has
// only ~163px of circumference to spend. One segment per note at 128 notes is
// 0.6px of ink with a 0.6px gap, which renders as a solid blur — the same
// picture the ring would draw for 90 or for 300. The count in the middle is
// the precise reading; the ring is the glance.
export const RING_MAX_SEGMENTS = 12;

// Fraction of each segment's share of the circle that is gap rather than ink.
const RING_GAP_RATIO = 0.4;

// Above this the count is shown as "99+". The disc has ~51 units of clear
// width and three digits at 19px take ~33, so four would still fit — but a
// second font size for a case that never arrives is a branch nobody tests, and
// the ring already carries "a lot" on its own.
export const COUNT_CAP = 99;

// The count as it appears in the disc: an exact figure, or the cap.
export function formatCount(count) {
  const notes = Math.max(0, Math.floor(Number(count) || 0));

  return notes > COUNT_CAP ? `${COUNT_CAP}+` : String(notes);
}

// Ring geometry for `count` notes, in user units of the 54-unit viewBox.
//
// Returns `{ segments, dash, gap }` for `stroke-dasharray="dash gap"`, and
// `segments: 0` for an empty Inbox — the caller draws that as one continuous
// muted circle, since a ring of nothing is a different statement from a ring
// of one.
//
// `strokeWidth` is subtracted from the dash and handed to the gap because the
// stroke is drawn with round caps, which add half a stroke width at each end
// of every dash. Without that the painted segment is longer than the requested
// dash and the gaps close up as the count climbs.
export function ringDashes(count, circumference, strokeWidth) {
  const notes = Math.max(0, Math.floor(Number(count) || 0));
  const segments = Math.min(notes, RING_MAX_SEGMENTS);

  if (segments === 0) return { segments: 0, dash: 0, gap: 0 };

  const step = circumference / segments;
  // A single segment would otherwise close into a full circle and lose its gap.
  const gap = Math.min(step * RING_GAP_RATIO + strokeWidth, step * 0.9);

  return { segments, dash: step - gap, gap };
}

// Compare two top-level folder names by the vault's canonical root order.
//
// `roots` is the roster from /api/explorer — [{key, label}] in the order the
// server says roots belong in. A vault can legitimately hold a folder that is
// not on it: a root left in another language by a language switch, or one typed
// by hand. Those sort alphabetically *after* the known roots rather than being
// dropped (which would hide notes) or leading (which would be noise).
//
// Sub-folders and notes are not affected — only the top level has an opinion.
export function compareRoots(roots) {
  const rank = new Map((roots || []).map((root, index) => [root.label, index]));

  return (a, b) => {
    const ra = rank.has(a) ? rank.get(a) : Infinity;
    const rb = rank.has(b) ? rank.get(b) : Infinity;

    if (ra !== rb) return ra - rb;

    return a.localeCompare(b);
  };
}

// Which of the offered paths this target may actually move to.
//
// A note may go anywhere. A folder may not go into itself or into its own
// descendants: renaming `Projects/api` to `Projects/api` does nothing, and to
// `Projects/api/v2` asks for a folder to become a child of itself. Pure, and
// given the list rather than fetching it, so the filter is testable on plain
// strings.
export function selectablePaths(paths, target) {
  if (!target || target.type !== "folder") return paths;
  const own = target.path || "";

  return paths.filter((path) => path !== own && !path.startsWith(own + "/"));
}

// Rows whose path contains the typed text, case-insensitively. An empty query
// matches everything rather than nothing — the list's job when the sheet opens
// is to show what exists.
export function filterPaths(paths, query) {
  const needle = (query || "").trim().toLowerCase();
  if (!needle) return paths;

  return paths.filter((path) => path.toLowerCase().includes(needle));
}

// How much of a note's text the card shows before "… more".
export const CLAMP_CHARS = 100;

// Split a note's text into what the card shows and what "more" reveals.
//
// Returns `{head, rest}` where `rest` is "" for a note short enough to show
// whole — which is also the signal that there is no control to render, so the
// caller never compares lengths itself.
//
// The cut moves back to the last space inside the limit rather than landing
// mid-word: `CLAMP_CHARS` is a budget, not a target, and a word sliced in half
// reads as a rendering fault. A single long token (a URL) has no space to fall
// back to, so it is cut at the limit — better a hard break than a 400-character
// "preview".
export function clampText(text, limit = CLAMP_CHARS) {
  const whole = text || "";
  if (whole.length <= limit) return { head: whole, rest: "" };
  const slice = whole.slice(0, limit);
  const space = slice.lastIndexOf(" ");
  const cut = space > Math.floor(limit / 2) ? space : limit;

  return { head: whole.slice(0, cut).trimEnd(), rest: whole.slice(cut).trimStart() };
}
