import { createContext, useContext, useReducer, useCallback, useEffect, useMemo, useRef } from "react";
import * as api from "../lib/api.js";

const AppContext = createContext(null);
export const useApp = () => useContext(AppContext);

const FILTER_KEY = "feedFolderFilter";

function loadFilter() {
  try {
    const raw = localStorage.getItem(FILTER_KEY);
    return raw ? new Set(JSON.parse(raw)) : null;
  } catch (e) { return null; }
}
function saveFilter(sel) {
  try {
    if (sel) localStorage.setItem(FILTER_KEY, JSON.stringify([...sel]));
    else localStorage.removeItem(FILTER_KEY);
  } catch (e) { /* ignore */ }
}

const initial = {
  view: "notes",            // notes | browser | map | search | chat
  prevView: "notes",        // last non-input view (for close/back)
  barMode: null,            // "search" | "chat" while the pill shows its input
  notes: [],                // browser tree + search source
  feed: null,               // full note cards; null = not loaded
  filterSel: loadFilter(),  // Set of included folder keys, or null = all
  stats: { notes: 0, links: 0, reminders: 0 },   // header stats (/api/header/stats)
  sheetNoteId: null,        // open note preview (null = closed)
  filterOpen: false,
  ctx: null,                // { target, rect } context menu
  pathTarget: null,         // change-path sheet target
  searchQuery: "",
  scoped: null,             // {notes, links} when a browser folder is selected
  chat: { threadId: null, messages: [], busy: false },
};

function reducer(s, a) {
  switch (a.type) {
    case "patch": return { ...s, ...a.patch };
    case "chat": return { ...s, chat: { ...s.chat, ...a.patch } };
    case "chatMsgs": return { ...s, chat: { ...s.chat, messages: a.fn(s.chat.messages) } };
    default: return s;
  }
}

// The bot bubble for a chat response: an answer (with citations) or a paused write.
function toBot(data) {
  if (data && data.status === "confirm" && data.action) return { role: "bot", action: data.action };
  if (data && data.reply) return { role: "bot", text: data.reply, citations: data.citations || [] };
  return { role: "bot", text: "The assistant is unavailable right now.", muted: true };
}

export function AppProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initial);
  const patch = useCallback((p) => dispatch({ type: "patch", patch: p }), []);
  const feedReq = useRef(0);
  const threadRef = useRef(null);   // chat thread id (avoids stale closures)
  const busyRef = useRef(false);    // guards against overlapping chat turns

  // ----- navigation -----
  const setView = useCallback((view) => {
    const isInput = view === "search" || view === "chat";
    patch({
      view,
      prevView: isInput ? state.prevView : view,
      barMode: isInput ? view : null,
      searchQuery: isInput ? "" : state.searchQuery,
    });
  }, [patch, state.prevView, state.searchQuery]);

  const closeMode = useCallback(() => setView(state.prevView), [setView, state.prevView]);
  const toggleMode = useCallback((mode) => {
    if (state.barMode === mode) closeMode(); else setView(mode);
  }, [state.barMode, closeMode, setView]);

  // ----- data -----
  const reload = useCallback(async () => {
    const [notes, feed] = await Promise.all([api.fetchNotes(), api.fetchFeed()]);
    patch({ notes, feed, scoped: null });
  }, [patch]);

  const setScoped = useCallback((s) => patch({ scoped: s }), [patch]);

  const refreshStats = useCallback(async () => {
    patch({ stats: await api.fetchStats() });
  }, [patch]);

  // ----- preview sheet -----
  const openNote = useCallback((id) => patch({ sheetNoteId: id }), [patch]);
  const closeNote = useCallback(() => patch({ sheetNoteId: null }), [patch]);

  // ----- context menu / change-path -----
  const openCtx = useCallback((target, rect) => patch({ ctx: { target, rect } }), [patch]);
  const closeCtx = useCallback(() => patch({ ctx: null }), [patch]);
  const openPath = useCallback((target) => patch({ ctx: null, pathTarget: target }), [patch]);
  const closePath = useCallback(() => patch({ pathTarget: null }), [patch]);

  // ----- filter -----
  const openFilter = useCallback(() => patch({ filterOpen: true }), [patch]);
  const closeFilter = useCallback(() => patch({ filterOpen: false }), [patch]);
  const setFilter = useCallback((sel) => { saveFilter(sel); patch({ filterSel: sel }); }, [patch]);

  const setSearchQuery = useCallback((q) => patch({ searchQuery: q }), [patch]);

  // ----- chat -----
  const runChat = useCallback(async (call, userMsg) => {
    if (busyRef.current) return;
    busyRef.current = true;
    dispatch({ type: "chat", patch: { busy: true } });
    dispatch({ type: "chatMsgs", fn: (m) => [...m, ...(userMsg ? [userMsg] : []), { role: "bot", pending: true }] });
    let data = null;
    try { data = await call(); } catch (e) { data = null; }
    if (data && data.thread_id) threadRef.current = data.thread_id;
    const bot = toBot(data);
    dispatch({ type: "chatMsgs", fn: (m) => [...m.filter((x) => !x.pending), bot] });
    dispatch({ type: "chat", patch: { busy: false, threadId: threadRef.current } });
    busyRef.current = false;
  }, []);

  const sendChat = useCallback((text) => {
    text = (text || "").trim();
    if (!text) return;
    runChat(() => api.chatSend(text, threadRef.current), { role: "user", text });
  }, [runChat]);

  const confirmChat = useCallback((approve) => {
    if (threadRef.current == null) return;
    runChat(() => api.chatConfirm(threadRef.current, approve), null);
  }, [runChat]);

  // ----- boot -----
  useEffect(() => { reload(); refreshStats(); /* eslint-disable-next-line */ }, []);

  const value = useMemo(() => ({
    state, patch, setView, closeMode, toggleMode, reload, refreshStats,
    openNote, closeNote, openCtx, closeCtx, openPath, closePath,
    openFilter, closeFilter, setFilter, setSearchQuery, sendChat, confirmChat, setScoped, feedReq,
  }), [state, patch, setView, closeMode, toggleMode, reload, refreshStats,
      openNote, closeNote, openCtx, closeCtx, openPath, closePath,
      openFilter, closeFilter, setFilter, setSearchQuery, sendChat, confirmChat, setScoped]);

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
