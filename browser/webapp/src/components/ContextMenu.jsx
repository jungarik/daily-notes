import { useEffect, useRef, useState } from "react";
import { useApp } from "../store/AppContext.jsx";
import { setNotePath, moveFolder, listPaths } from "../lib/api.js";
import { selectablePaths, filterPaths } from "../lib/format.js";

// The menu's icons, in the app's one icon style: a 24-viewBox inline SVG,
// `fill: none`, `stroke: currentColor`, 1.8 stroke, round caps — the same
// recipe the dock's tabs and the Add-note page's side buttons use, so a
// control reads as part of this app wherever it appears. They replaced emoji
// (✏️ 📁 🗑), which render in a different style on every platform, carry their
// own colour no matter what the item is doing, and sat a few pixels off the
// text baseline. `currentColor` is what lets the Delete item's glyph go red
// with its label instead of needing a second rule.
//
// The folder path is deliberately the same one as `AddNote`'s path button:
// the same object should not be drawn two ways.
const EditGlyph = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3Z" />
    <path d="M14.5 6.5l3 3" />
  </svg>
);
const FolderGlyph = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4L11 7.5h8.5A1.5 1.5 0 0 1 21 9v8.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5v-11Z" />
  </svg>
);
const TrashGlyph = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9.5 7V5.5A1.5 1.5 0 0 1 11 4h2a1.5 1.5 0 0 1 1.5 1.5V7" />
    <path d="M6 7l1 12a1.5 1.5 0 0 0 1.5 1.4h7A1.5 1.5 0 0 0 17 19L18 7" />
    <path d="M10.5 11v6M13.5 11v6" />
  </svg>
);

// The ⋮ context menu (positioned at the tapped element) + its two sheets:
// change-path, and the delete confirmation.
export default function ContextMenu() {
  const { state, closeCtx, openPath, closePath, openDelete, closeDelete,
          removeNote, reload, openAddNote } = useApp();
  const ctx = state.ctx;            // { target, rect } or null
  const menuRef = useRef(null);
  const [pos, setPos] = useState({ left: -9999, top: -9999 });

  // Position after render so we can measure the menu, flipping up if no room.
  useEffect(() => {
    if (!ctx) return;
    const menu = menuRef.current; if (!menu) return;
    const r = ctx.rect;
    const mw = menu.offsetWidth, mh = menu.offsetHeight;
    const left = Math.max(8, Math.min(r.right - mw, window.innerWidth - mw - 8));
    let top = r.bottom + 4;
    if (top + mh > window.innerHeight - 8) top = r.top - mh - 4;
    setPos({ left, top: Math.max(8, top) });
  }, [ctx]);

  // Dismiss on any outside click (deferred so the opening click doesn't close it).
  useEffect(() => {
    if (!ctx) return;
    const onDoc = (e) => { if (menuRef.current && !menuRef.current.contains(e.target)) closeCtx(); };
    const id = setTimeout(() => document.addEventListener("click", onDoc), 0);
    return () => { clearTimeout(id); document.removeEventListener("click", onDoc); };
  }, [ctx, closeCtx]);

  return (
    <>
      {ctx && (
        <div className="ctx-menu show" ref={menuRef} style={{ left: pos.left, top: pos.top }}>
          {ctx.target.type === "note" && (
            <button className="ctx-item" onClick={() => openAddNote(ctx.target.id)}>
              <EditGlyph />Edit
            </button>
          )}
          <button className="ctx-item" onClick={() => openPath(ctx.target)}>
            <FolderGlyph />Path
          </button>
          {/* Notes only. A folder here is not an object — it is a path prefix
              on some set of notes — so a folder Delete would silently mean
              "destroy everything filed under this", which is far too much to
              sit one tap away in the same menu as a rename. */}
          {ctx.target.type === "note" && (
            <button className="ctx-item danger" onClick={() => openDelete(ctx.target)}>
              <TrashGlyph />Delete
            </button>
          )}
        </div>
      )}
      <PathSheet target={state.pathTarget} onClose={closePath} onSaved={reload} />
      <DeleteSheet target={state.deleteTarget} onClose={closeDelete} onConfirm={removeNote} />
    </>
  );
}

// The confirmation. Deliberately the same bottom sheet as the change-path form
// rather than a native `confirm()`: that renders as browser chrome inside
// Telegram's webview, cannot be coloured, and is suppressed outright by some
// in-app webviews — which would make Delete appear to do nothing at all.
function DeleteSheet({ target, onClose, onConfirm }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (target) { setBusy(false); setErr(""); }
  }, [target]);

  // Not named `confirm` — that shadows `window.confirm`, and a reader skimming
  // for whether this uses a native dialog would find the wrong thing.
  const runDelete = async () => {
    if (!target || busy) return;
    setBusy(true);
    try {
      await onConfirm(target.id);
    } catch (e) {
      setErr("Couldn't delete. Try again.");
      setBusy(false);
    }
  };

  const open = !!target;
  return (
    <>
      <div className={"sheet-backdrop" + (open ? " show" : "")} onClick={busy ? undefined : onClose} />
      <div className={"sheet" + (open ? " show" : "")} id="deleteSheet">
        <div className="grip" />
        <div className="card-title">Delete “{(target && target.name) || "note"}”?</div>
        <div className="delete-warning">
          This can’t be undone. Its photos, voice recording, reminders and links
          to other notes are deleted with it.
        </div>
        <div className="path-error">{err}</div>
        <div className="path-actions">
          <button className="path-btn ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="path-btn danger" onClick={runDelete} disabled={busy}>
            {busy ? "Deleting…" : "Delete"}
          </button>
        </div>
      </div>
    </>
  );
}

// The change-path sheet: a combobox, not a dropdown beside a text field.
//
// The input is both the filter and the answer. Typing narrows the list below;
// tapping a row fills the input rather than saving, because the common move is
// to pick an existing folder and then extend it (`Projects/api` →
// `Projects/api/v2`), which a save-on-tap list makes impossible. Anything typed
// that matches no row is simply a new path — the server validates the root
// either way, so there is no "new folder" mode to switch into.
function PathSheet({ target, onClose, onSaved }) {
  const [val, setVal] = useState("");
  const [err, setErr] = useState("");
  const [paths, setPaths] = useState([]);
  // Whether the user has touched the input since the sheet opened. The list
  // stays hidden until they have: on open the input holds the current path,
  // and a list filtered by it would show that path and its children — the one
  // place the note already is. Hiding it keeps the sheet the size it was and
  // makes the list appear as an answer to typing rather than as furniture.
  const [touched, setTouched] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    if (target) {
      setVal(target.path || ""); setErr(""); setTouched(false);
      // Focus *and select*: the path is usually being replaced rather than
      // edited, so the first keystroke or Backspace should clear the whole
      // thing. `select()` keeps it readable until then, where clearing the
      // input on open would throw away the only reference to where the note
      // currently lives. The 60ms wait is the sheet's slide-in — focusing
      // mid-transition lands the caret in a moving element on iOS.
      setTimeout(() => {
        const input = inputRef.current;
        if (!input) return;
        input.focus();
        input.select();
      }, 60);
    }
  }, [target]);

  const edit = (next) => { setVal(next); setErr(""); setTouched(true); };

  // Read on open, not on mount: the vault changes while the app is up, and a
  // roster fetched once at boot goes stale exactly when the user has just
  // filed something new and reaches for it.
  useEffect(() => {
    if (!target) return;
    let live = true;
    listPaths().then((list) => { if (live) setPaths(list); });

    return () => { live = false; };
  }, [target]);

  const options = filterPaths(selectablePaths(paths, target), val);
  // The typed path is already the input's value, so a row repeating it back
  // is a tap that changes nothing.
  const suggestions = touched
    ? options.filter((path) => path !== (val || "").trim())
    : [];

  const save = async () => {
    if (!target) return;
    const v = (val || "").trim();
    if (!v) { setErr("Enter a path."); return; }
    try {
      if (target.type === "note") await setNotePath(target.id, v);
      else await moveFolder(target.path, v);
    } catch (e) {
      setErr(String(e).includes("422") ? "Path must start with a root folder." : "Couldn't save. Try again.");
      return;
    }
    onClose();
    await onSaved();
  };

  const open = !!target;
  return (
    <>
      <div className={"sheet-backdrop" + (open ? " show" : "")} onClick={onClose} />
      <div className={"sheet" + (open ? " show" : "")} id="pathSheet">
        <div className="grip" />
        <div className="card-title">{target && target.type === "folder" ? "Rename folder path" : "Change note path"}</div>
        <div className="path-field">
          <input ref={inputRef} className="path-input" type="text" value={val}
            autoComplete="off" autoCapitalize="off" spellCheck={false} placeholder="Projects/idea"
            onChange={(e) => edit(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") save(); }} />
          {/* Not a `type="reset"`, and not hidden when the field is empty: a
              control that disappears under your thumb is one the user stops
              trusting. It empties the field and refocuses, which also opens
              the list — an empty query is every path. */}
          {val !== "" && (
            <button className="path-clear" aria-label="Clear path" onClick={() => {
              edit("");
              if (inputRef.current) inputRef.current.focus();
            }}>✕</button>
          )}
        </div>
        {suggestions.length > 0 && (
          <div className="path-list">
            {suggestions.map((path) => (
              <button key={path} className="path-opt" onClick={() => {
                setVal(path);
                setErr("");
                if (inputRef.current) inputRef.current.focus();
              }}>{path}</button>
            ))}
          </div>
        )}
        <div className="path-error">{err}</div>
        <div className="path-actions">
          <button className="path-btn ghost" onClick={onClose}>Cancel</button>
          <button className="path-btn primary" onClick={save}>Save</button>
        </div>
      </div>
    </>
  );
}
