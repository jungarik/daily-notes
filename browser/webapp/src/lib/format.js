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
