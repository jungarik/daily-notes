import { useEffect, useRef, useState } from "react";
import { useApp } from "../store/AppContext.jsx";
import { setNotePath, moveFolder } from "../lib/api.js";

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
            <button className="ctx-item" onClick={() => openAddNote(ctx.target.id)}>✏️ Edit</button>
          )}
          <button className="ctx-item" onClick={() => openPath(ctx.target)}>📁 Change path</button>
          {/* Notes only. A folder here is not an object — it is a path prefix
              on some set of notes — so a folder Delete would silently mean
              "destroy everything filed under this", which is far too much to
              sit one tap away in the same menu as a rename. */}
          {ctx.target.type === "note" && (
            <button className="ctx-item danger" onClick={() => openDelete(ctx.target)}>
              🗑 Delete
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

function PathSheet({ target, onClose, onSaved }) {
  const [val, setVal] = useState("");
  const [err, setErr] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    if (target) {
      setVal(target.path || ""); setErr("");
      setTimeout(() => inputRef.current && inputRef.current.focus(), 60);
    }
  }, [target]);

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
        <input ref={inputRef} className="path-input" type="text" value={val}
          autoComplete="off" autoCapitalize="off" spellCheck={false} placeholder="Projects/idea"
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") save(); }} />
        <div className="path-error">{err}</div>
        <div className="path-actions">
          <button className="path-btn ghost" onClick={onClose}>Cancel</button>
          <button className="path-btn primary" onClick={save}>Save</button>
        </div>
      </div>
    </>
  );
}
