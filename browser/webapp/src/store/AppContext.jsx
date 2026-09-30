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
  view: "notes",            // notes | explorer | map | search | chat
  prevView: "notes",        // last non-input view (for close/back)
  barMode: null,            // "search" | "chat" while the pill shows its input
  notes: [],                // explorer tree + search source
  roots: [],                // vault root folders, in canonical order
  feed: null,               // full note cards; null = not loaded
  filterSel: loadFilter(),  // Set of included folder keys, or null = all
  stats: [],                // header root-folder counts (/api/header/stats)
  sheetNoteId: null,        // open note preview (null = closed)
  filterOpen: false,
  addNoteOpen: false,       // the Add note page (a full-screen overlay)
  ctx: null,                // { target, rect } context menu
  pathTarget: null,         // change-path sheet target
  deleteTarget: null,       // delete-confirmation sheet target (notes only)
  searchQuery: "",
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

// The bot bubble for a chat response: an answer (with citations) or a proposed
// action (handed off to the enrich agent) awaiting the user's confirmation.
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
  // The Add note textarea. It lives here rather than inside AddNote because
  // `openAddNote` has to focus it, and that has to happen in the click handler
  // of the button that opens the page — see the comment there.
  const addNoteInputRef = useRef(null);

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
    const [explorer, feed] = await Promise.all([api.fetchNotes(), api.fetchFeed()]);
    patch({ notes: explorer.notes || [], roots: explorer.roots || [], feed });
  }, [patch]);


  const refreshStats = useCallback(async () => {
    patch({ stats: (await api.fetchStats()).stats || [] });
  }, [patch]);

  // Deleting lives here rather than in the sheet because the aftermath is all
  // store state: the preview may be showing the note that just went, and both
  // the feed and the header counts are now stale. Throws on failure so the
  // sheet can say so — a delete that fails silently leaves the user believing
  // the note is gone.
  const removeNote = useCallback(async (id) => {
    await api.deleteNote(id);
    patch({
      deleteTarget: null,
      sheetNoteId: state.sheetNoteId === id ? null : state.sheetNoteId,
    });
    await Promise.all([reload(), refreshStats()]);
  }, [patch, reload, refreshStats, state.sheetNoteId]);

  // ----- preview sheet -----
  const openNote = useCallback((id) => patch({ sheetNoteId: id }), [patch]);
  const closeNote = useCallback(() => patch({ sheetNoteId: null }), [patch]);

  // ----- context menu / change-path -----
  const openCtx = useCallback((target, rect) => patch({ ctx: { target, rect } }), [patch]);
  const closeCtx = useCallback(() => patch({ ctx: null }), [patch]);
  const openPath = useCallback((target) => patch({ ctx: null, pathTarget: target }), [patch]);
  const closePath = useCallback(() => patch({ pathTarget: null }), [patch]);

  // Delete closes the menu the same way change-path does, and the confirmation
  // sheet is what actually calls the API.
  const openDelete = useCallback((target) => patch({ ctx: null, deleteTarget: target }), [patch]);
  const closeDelete = useCallback(() => patch({ deleteTarget: null }), [patch]);

  // ----- filter -----
  const openFilter = useCallback(() => patch({ filterOpen: true }), [patch]);
  const closeFilter = useCallback(() => patch({ filterOpen: false }), [patch]);

  // The Add note page covers the whole screen rather than taking a slot in
  // `view`, so closing it needs no `prevView` dance — whatever tab was behind
  // it is still the current one.
  // Focus first, then open. The order is the whole trick: iOS and Telegram's
  // webview raise the keyboard only for a `focus()` made during a user gesture,
  // and `patch` is asynchronous — anything that waits for the re-render has
  // already lost the gesture and gets a caret with no keyboard. AddNote is
  // always mounted precisely so there is something to focus at this moment.
  const openAddNote = useCallback(() => {
    if (addNoteInputRef.current) addNoteInputRef.current.focus();

    patch({ addNoteOpen: true });
  }, [patch]);

  const closeAddNote = useCallback(() => {
    if (addNoteInputRef.current) addNoteInputRef.current.blur();

    patch({ addNoteOpen: false });
  }, [patch]);
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

  const confirmChat = useCallback((approve, selection) => {
    if (threadRef.current == null) return;
    runChat(() => api.chatConfirm(threadRef.current, approve, selection), null);
  }, [runChat]);

  // ----- boot -----
  useEffect(() => { reload(); refreshStats(); /* eslint-disable-next-line */ }, []);

  const value = useMemo(() => ({
    state, patch, setView, closeMode, toggleMode, reload, refreshStats,
    openNote, closeNote, openCtx, closeCtx, openPath, closePath,
    openFilter, closeFilter, setFilter, setSearchQuery, sendChat, confirmChat, feedReq,
    openAddNote, closeAddNote, openDelete, closeDelete, removeNote,
    addNoteInputRef,
  }), [state, patch, setView, closeMode, toggleMode, reload, refreshStats,
      openNote, closeNote, openCtx, closeCtx, openPath, closePath,
      openFilter, closeFilter, setFilter, setSearchQuery, sendChat, confirmChat,
      openAddNote, closeAddNote, openDelete, closeDelete, removeNote]);

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
