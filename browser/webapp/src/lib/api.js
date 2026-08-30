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

// Attachment URLs come back relative (/api/notecard/attachments/…); resolve them
// against the API origin.
export function mediaUrl(u) {
  if (!u) return u;
  if (/^https?:\/\//.test(u)) return u;
  return API_BASE + u;
}

// --- domain helpers (each degrades to a sensible default) ---
// Endpoints are being migrated to per-section surfaces (/api/<section>). Migrated
// so far: feed → /api/feed (attachment proxy → /api/notecard).
export const fetchNotes = () => apiGet("/api/notes").catch(() => []);
export const fetchFeed = () => apiGet("/api/feed").catch(() => []);
export const fetchNote = (id) => apiGet("/api/notes/" + encodeURIComponent(id)).catch(() => null);
export const fetchGraph = () => apiGet("/api/notes/graph").catch(() => ({ nodes: [], edges: [] }));
export const fetchReminderCount = () => apiGet("/api/reminders/count").then((d) => d.count || 0).catch(() => 0);
export const setNotePath = (id, path) => apiPost("/api/notes/" + encodeURIComponent(id) + "/path", { path });
export const moveFolder = (old_path, new_path) => apiPost("/api/notes/folder/move", { old_path, new_path });
export const chatSend = (message, thread_id) => apiPost("/api/chat", { message, thread_id });
export const chatConfirm = (thread_id, approve) => apiPost("/api/chat/confirm", { thread_id, approve });
