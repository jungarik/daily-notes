import { useEffect, useRef, useState } from "react";
import { useApp } from "../store/AppContext.jsx";
import { setNotePath, moveFolder } from "../lib/api.js";

// The ⋮ context menu (positioned at the tapped element) + the change-path sheet.
export default function ContextMenu() {
  const { state, closeCtx, openPath, closePath, reload } = useApp();
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
          <button className="ctx-item" onClick={() => openPath(ctx.target)}>📁 Change path</button>
        </div>
      )}
      <PathSheet target={state.pathTarget} onClose={closePath} onSaved={reload} />
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
