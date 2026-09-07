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
  const key = String(path || "Inbox").trim() || "Inbox";
  let h = 0;

  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;

  return "hsl(" + (h % 360) + "," + sat + "%," + light + "%)";
}

// A note's folder key for the filter (its path, or a bucket for unsorted notes).
export const notePathKey = (d) => (d && d.path) || "(unsorted)";

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
