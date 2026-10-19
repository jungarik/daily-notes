import { useMemo, useRef, useState } from "react";
import { useApp } from "../store/AppContext.jsx";
import { compareRoots } from "../lib/format.js";

// --- tree building for the explorer view ---
function buildTree(notes) {
  const root = { folders: {}, files: [] };
  for (const n of notes) {
    // Every note here has a path: /api/explorer omits the un-filed ones.
    const path = (n.path || "").trim();
    const parts = path.split("/").map((p) => p.trim()).filter(Boolean);
    let node = root;
    for (const part of parts) {
      node.folders[part] = node.folders[part] || { folders: {}, files: [] };
      node = node.folders[part];
    }
    node.files.push(n);
  }
  return root;
}

const FolderSvg = () => (
  <svg className="ico" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6z" /></svg>
);
const FileSvg = () => (
  <svg className="ico" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M6 2h8l4 4v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z" /><path d="M14 2v5h5" /><line x1="8" y1="12" x2="14" y2="12" /><line x1="8" y1="15.5" x2="14" y2="15.5" /><line x1="8" y1="19" x2="11.5" y2="19" /></svg>
);

// Selection is one value for the whole tree, owned by `Explorer`: the key of the
// last row tapped. It used to be a `sel` flag inside every `Folder` that was only
// ever set to true, so each folder you had tapped stayed highlighted for good
// and a note row had no highlight at all.
const folderKey = (path) => "folder:" + path;
const noteKey = (id) => "note:" + id;

// Same numbers as the map's long press (`graph/engine.js`): hold 450 ms, and a
// finger that wanders more than 6 px is scrolling, not pressing.
const LONG_PRESS_MS = 450;
const TAP_SLOP = 6;

function FileRow({ note, selected, onSelect }) {
  const { openNote, openCtx, openViewNote } = useApp();
  // Highlights the row while the hold is running, so the press is visible
  // before it fires.
  const [pressing, setPressing] = useState(false);
  const press = useRef({ timer: null, x: 0, y: 0, fired: false });
  // The server labels every row with the note's opening words and never sends
  // an empty one (it falls back to "untitled" for a note that is only photos),
  // so there is nothing to default here.
  const label = note.label;

  const cancelPress = () => {
    clearTimeout(press.current.timer);
    press.current.timer = null;
    setPressing(false);
  };

  const startPress = (e) => {
    // The ⋮ has its own tap; a hold on it is not a press on the row.
    if (e.target.closest(".dots")) return;

    press.current = { timer: null, x: e.clientX, y: e.clientY, fired: false };
    setPressing(true);
    press.current.timer = setTimeout(() => {
      press.current.fired = true;
      press.current.timer = null;
      setPressing(false);
      openViewNote(note.id);
    }, LONG_PRESS_MS);
  };

  const movePress = (e) => {
    if (press.current.timer === null) return;
    if (Math.hypot(e.clientX - press.current.x, e.clientY - press.current.y) > TAP_SLOP) cancelPress();
  };

  return (
    <div className={"row file" + (selected === noteKey(note.id) ? " selected" : "") + (pressing ? " pressing" : "")} data-id={note.id}
      onPointerDown={startPress}
      onPointerMove={movePress}
      onPointerUp={cancelPress}
      onPointerCancel={cancelPress}
      onPointerLeave={cancelPress}
      // The browser's own long-press menu would sit on top of the page we open.
      onContextMenu={(e) => e.preventDefault()}
      onClick={() => {
        // The release that ends a long press still arrives as a click; the page
        // is already open, so it must not also open the preview sheet.
        if (press.current.fired) { press.current.fired = false; return; }

        onSelect(noteKey(note.id));
        openNote(note.id);
      }}>
      <FileSvg />
      <span className="name">{label}<span className="ext">.md</span></span>
      <span className="dots" role="button" aria-label="menu"
        onClick={(e) => { e.stopPropagation(); openCtx({ type: "note", id: note.id, path: note.path, name: label }, e.currentTarget.getBoundingClientRect()); }}>⋮</span>
    </div>
  );
}

function Folder({ name, node, path, selected, onSelect }) {
  const { openCtx } = useApp();
  // Open and selected are independent: opening a folder does not collapse the
  // others, and re-tapping the selected one still toggles it and stays selected.
  const [open, setOpen] = useState(false);
  const isRoot = path.indexOf("/") < 0;
  const folderNames = Object.keys(node.folders).sort((a, b) => a.localeCompare(b));
  // Sorted by the label, which is now the note's first words rather than an
  // enriched title — so the tree reads alphabetically by how each note opens.
  const files = node.files.slice().sort((a, b) => (a.label || "").localeCompare(b.label || ""));
  return (
    <div className={"folder" + (open ? " open" : "")}>
      <div className={"row" + (selected === folderKey(path) ? " selected" : "")}
        onClick={() => { setOpen((o) => !o); onSelect(folderKey(path)); }}>
        <FolderSvg />
        <span className="name">{name}</span>
        {!isRoot && (
          <span className="dots" role="button" aria-label="menu"
            onClick={(e) => { e.stopPropagation(); openCtx({ type: "folder", path, name }, e.currentTarget.getBoundingClientRect()); }}>⋮</span>
        )}
      </div>
      <div className="children">
        {folderNames.map((f) => (
          <Folder key={f} name={f} node={node.folders[f]} path={path + "/" + f}
            selected={selected} onSelect={onSelect} />
        ))}
        {files.map((file) => <FileRow key={file.id} note={file} selected={selected} onSelect={onSelect} />)}
      </div>
    </div>
  );
}

export default function Explorer({ hidden }) {
  const { state } = useApp();
  // The one highlighted row; the Explorer stays mounted while hidden, so it
  // survives a trip to another tab.
  const [selected, setSelected] = useState(null);
  const notes = state.notes || [];
  const root = useMemo(() => buildTree(notes), [notes]);
  // Only the top level follows the vault's order; `Folder` keeps sorting its
  // own children alphabetically.
  const rootFolders = Object.keys(root.folders).sort(compareRoots(state.roots));
  const empty = !rootFolders.length && !root.files.length;
  return (
    <div id="tree" className={"view" + (hidden ? " hidden" : "")}>
      {empty
        ? <div className="empty">No notes yet.<br />Send one to the bot to get started.</div>
        : (<>
            {rootFolders.map((f) => (
              <Folder key={f} name={f} node={root.folders[f]} path={f}
                selected={selected} onSelect={setSelected} />
            ))}
            {root.files.map((file) => <FileRow key={file.id} note={file} selected={selected} onSelect={setSelected} />)}
          </>)}
    </div>
  );
}
