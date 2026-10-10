// One place for all API access. The app is a separate static host that calls
// the API cross-origin; every call carries the Telegram initData header.
import { INIT_DATA } from "./telegram.js";

// Set VITE_API_BASE at build time to the API's public origin (CORS is enabled
// there). Falls back to window.__API_BASE__ or the page origin for local dev.
export const API_BASE = (
  import.meta.env.VITE_API_BASE ||
  (typeof window !== "undefined" && window.__API_BASE__) ||
  (typeof location !== "undefined" && location.origin) || ""
).replace(/\/$/, "");

function headers(json) {
  const h = { "X-Telegram-Init-Data": INIT_DATA };
  if (json) h["Content-Type"] = "application/json";
  return h;
}

export async function apiGet(path) {
  const res = await fetch(API_BASE + path, { headers: headers() });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

export async function apiPost(path, body) {
  const res = await fetch(API_BASE + path, {
    method: "POST", headers: headers(true), body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

export async function apiPut(path, body) {
  const res = await fetch(API_BASE + path, {
    method: "PUT", headers: headers(true), body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

// Separate from apiPost because a 204 has no body to parse: `res.json()` on an
// empty response rejects, which would report a successful delete as a failure.
export async function apiDelete(path) {
  const res = await fetch(API_BASE + path, { method: "DELETE", headers: headers() });
  if (!res.ok) throw new Error("HTTP " + res.status);
}

// Attachment URLs come back relative (/api/notecard/attachments/…); resolve them
// against the API origin.
export function mediaUrl(u) {
  if (!u) return u;
  if (/^https?:\/\//.test(u)) return u;
  return API_BASE + u;
}

// --- domain helpers (each degrades to a sensible default) ---
// Each web-app section calls its own /api/<section> surface (the endpoints.py in
// the matching api/<section>/ folder). Attachment proxy lives in the notecard
// section. Chat is on /api/chat/v2 — the agent-farm surface; /api/chat (v1) is
// still mounted on the API while v2 is proven, so a revert is a URL change.
export const fetchNotes = () => apiGet("/api/explorer").catch(() => ({ notes: [], roots: [] }));
export const fetchFeed = () => apiGet("/api/feed").catch(() => []);
export const fetchNote = (id) => apiGet("/api/notesheet/" + encodeURIComponent(id)).catch(() => null);
export const fetchGraph = () => apiGet("/api/mapview/graph").catch(() => ({ nodes: [], edges: [] }));
export const fetchStats = () => apiGet("/api/header/stats").catch(() => ({ stats: [] }));
export const searchNotes = (q) => apiGet("/api/search?q=" + encodeURIComponent(q)).catch(() => []);
// The two path wheels' rosters, each its own request: the root folders (plus
// where a note goes when nobody picks), and the sub-folders already in use
// under one root. Their own endpoints rather than the ⋮ menu's: the editor's
// section owns its reads. Both resolve to the same `{items, initial}` shape so
// `PathWheel` does not care which wheel it is.
export const listAddNoteRoots = () =>
  apiGet("/api/addnote/roots")
    .then((r) => ({ items: (r && r.roots) || [], initial: (r && r.default_root) || "" }))
    .catch(() => ({ items: [], initial: "" }));
export const listAddNoteChildren = (root) =>
  apiGet("/api/addnote/children?root=" + encodeURIComponent(root))
    .then((r) => ({ items: (r && r.children) || [], initial: "" }))
    .catch(() => ({ items: [], initial: "" }));
// Saving from the Add note page. Two verbs for two situations, chosen by the
// caller on whether it has an id — not merged into one "upsert", because a
// POST that silently updated (or a PUT that silently created) is the kind of
// endpoint nobody can reason about from the call site.
//
// Both answer with the stored note, which is not what was sent: an empty path
// came back as the default folder and a typed one came back normalised.
// Neither has a `.catch` — a save that quietly resolved would close the page
// over text that never reached the server.
export const createNote = (body) => apiPost("/api/addnote", body);
export const saveNote = (id, body) =>
  apiPut("/api/addnote/" + encodeURIComponent(id), body);
// The note the Add note page opens for editing. No `.catch` — the page tells
// the user it could not load rather than opening a blank editor that looks
// like an empty note.
export const fetchEditableNote = (id) =>
  apiGet("/api/addnote/" + encodeURIComponent(id));
// The change-path sheet's two selectors, each its own read: the root folders,
// and the sub-folders already in use under one root. Both fall back to an empty
// list — the root field then accepts a typed root and the sub-folder a typed
// name, so a failed read costs the suggestions, not the ability to move a note.
export const listRoots = () =>
  apiGet("/api/contextmenu/roots").then((r) => (r && r.roots) || []).catch(() => []);
export const listChildren = (root) =>
  apiGet("/api/contextmenu/children?root=" + encodeURIComponent(root))
    .then((r) => (r && r.children) || [])
    .catch(() => []);
export const setNotePath = (id, path) => apiPost("/api/contextmenu/notes/" + encodeURIComponent(id) + "/path", { path });
export const moveFolder = (old_path, new_path) => apiPost("/api/contextmenu/folder/move", { old_path, new_path });
// No `.catch` here, unlike the reads above: a delete that quietly resolved
// would leave the note on screen with the user believing it is gone.
export const deleteNote = (id) => apiDelete("/api/contextmenu/notes/" + encodeURIComponent(id));
export const chatSend = (message, thread_id) => apiPost("/api/chat/v2", { message, thread_id });
export const chatConfirm = (thread_id, approve, selection) =>
  apiPost("/api/chat/v2/confirm", { thread_id, approve, selection: selection ?? null });
