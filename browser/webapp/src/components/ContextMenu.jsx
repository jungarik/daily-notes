import { useEffect, useRef, useState } from "react";
import { useApp } from "../store/AppContext.jsx";
import { setNotePath, moveFolder, listRoots, listChildren } from "../lib/api.js";
import { splitPath, joinPath, swapRoot, filterNames } from "../lib/format.js";

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

// The change-path sheet: two stacked comboboxes, the root folder over the
// sub-folder under it.
//
// The path is two levels deep, so it is edited as two fields rather than one
// string. The root field offers the vault's fixed roots (no typing — the server
// rejects an unknown root); the sub-folder field offers what already exists
// under the chosen root and accepts a new name. Each field's list opens on
// focus and tapping a row fills the field. Choosing a different root clears the
// sub-folder, so "Projects/api" never survives a move to "Areas"; an empty
// sub-folder is the root itself.
//
// A folder is a path prefix, not a note, so it only moves between roots: its
// sheet has the root field alone, and the rest of its path travels with it
// (`Projects/api` to `Areas` is `Areas/api`).
function PathSheet({ target, onClose, onSaved }) {
  const isFolder = !!target && target.type === "folder";
  const [root, setRoot] = useState("");
  const [child, setChild] = useState("");
  const [err, setErr] = useState("");
  const [roots, setRoots] = useState([]);
  const [children, setChildren] = useState([]);
  // Which field's list is showing: "root" | "child" | "". One value — only one
  // list is ever open, and it closes when its field loses focus.
  const [openField, setOpenField] = useState("");

  useEffect(() => {
    if (!target) return;
    const current = splitPath(target.path);

    setRoot(current.root);
    setChild(target.type === "folder" ? "" : current.child);
    setErr("");
    setOpenField("");
  }, [target]);

  // Read on open, not on mount: the vault changes while the app is up, and a
  // roster fetched once at boot goes stale exactly when the user has just
  // filed something new and reaches for it.
  useEffect(() => {
    if (!target) return;
    let live = true;
    listRoots().then((list) => { if (live) setRoots(list); });

    return () => { live = false; };
  }, [target]);

  // The sub-folders of whichever root is chosen, re-read when it changes. A
  // folder has no sub-folder field, so it reads none.
  useEffect(() => {
    if (!target || isFolder || !root) { setChildren([]); return; }
    let live = true;
    listChildren(root).then((list) => { if (live) setChildren(list); });

    return () => { live = false; };
  }, [target, isFolder, root]);

  const pickRoot = (next) => {
    if (next !== root) setChild("");
    setRoot(next);
    setErr("");
    setOpenField("");
  };

  const pickChild = (next) => {
    setChild(next);
    setErr("");
    setOpenField("");
  };

  // Rows are tapped, not typed: keeping the mousedown from moving focus is what
  // stops the field's blur closing the list before the tap lands.
  const keepFocus = (e) => e.preventDefault();

  // The current choice is already in the field, so a row repeating it is a tap
  // that changes nothing.
  const rootOptions = roots.filter((name) => name !== root);
  const childOptions = filterNames(children, child).filter((name) => name !== child.trim());

  const save = async () => {
    if (!target) return;
    const chosenRoot = root.trim();
    if (!chosenRoot) { setErr("Pick a root folder."); return; }
    const next = isFolder ? swapRoot(target.path, chosenRoot) : joinPath(chosenRoot, child.trim());
    if (isFolder && next === target.path) { setErr("Pick a different root folder."); return; }
    try {
      if (target.type === "note") await setNotePath(target.id, next);
      else await moveFolder(target.path, next);
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
        <div className="card-title">{isFolder ? "Move folder" : "Change note path"}</div>
        <div className="path-field">
          {/* Read-only while there is a roster to pick from; if the read failed
              the field falls back to typing, and the server validates. */}
          <input className="path-input" type="text" value={root}
            readOnly={roots.length > 0}
            autoComplete="off" autoCapitalize="off" spellCheck={false} placeholder="Folder"
            aria-label="Folder"
            onFocus={() => setOpenField("root")}
            onBlur={() => setOpenField("")}
            onChange={(e) => { setRoot(e.target.value); setErr(""); }}
            onKeyDown={(e) => { if (e.key === "Enter") save(); }} />
        </div>
        {openField === "root" && rootOptions.length > 0 && (
          <div className="path-list">
            {rootOptions.map((name) => (
              <button key={name} className="path-opt" onMouseDown={keepFocus}
                onClick={() => pickRoot(name)}>{name}</button>
            ))}
          </div>
        )}
        {!isFolder && (
          <div className="path-field">
            <input className="path-input" type="text" value={child}
              disabled={!root.trim()}
              autoComplete="off" autoCapitalize="off" spellCheck={false}
              placeholder="Sub-folder (optional)" aria-label="Sub-folder"
              onFocus={() => setOpenField("child")}
              onBlur={() => setOpenField("")}
              // A name has no slash: it would be a third level hiding in the
              // second, so it is dropped as it is typed.
              onChange={(e) => { setChild(e.target.value.replace(/[\\/]/g, "")); setErr(""); }}
              onKeyDown={(e) => { if (e.key === "Enter") save(); }} />
            {/* Not hidden when the field is empty: a control that disappears
                under your thumb is one the user stops trusting. */}
            {child !== "" && (
              <button className="path-clear" aria-label="Clear sub-folder"
                onMouseDown={keepFocus} onClick={() => { setChild(""); setErr(""); }}>✕</button>
            )}
          </div>
        )}
        {!isFolder && openField === "child" && childOptions.length > 0 && (
          <div className="path-list">
            {childOptions.map((name) => (
              <button key={name} className="path-opt" onMouseDown={keepFocus}
                onClick={() => pickChild(name)}>{name}</button>
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
