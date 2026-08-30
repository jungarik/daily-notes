import { useMemo, useState } from "react";
import { useApp } from "../store/AppContext.jsx";

// --- tree building (mirrors the vanilla browser) ---
function buildTree(notes) {
  const root = { folders: {}, files: [] };
  for (const n of notes) {
    const path = ((n.path || "Inbox").trim()) || "Inbox";
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
function countNotes(node) {
  let c = node.files.length;
  for (const k in node.folders) c += countNotes(node.folders[k]);
  return c;
}
function countLinks(node) {
  let c = 0;
  for (const f of node.files) c += f.links || 0;
  for (const k in node.folders) c += countLinks(node.folders[k]);
  return c;
}

const FolderSvg = () => (
  <svg className="ico" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6z" /></svg>
);
const FileSvg = () => (
  <svg className="ico" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M6 2h8l4 4v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z" /><path d="M14 2v5h5" /><line x1="8" y1="12" x2="14" y2="12" /><line x1="8" y1="15.5" x2="14" y2="15.5" /><line x1="8" y1="19" x2="11.5" y2="19" /></svg>
);

function FileRow({ note }) {
  const { openNote, openCtx } = useApp();
  const title = (note.title && note.title.trim()) || "untitled";
  return (
    <div className="row file" data-id={note.id} onClick={() => openNote(note.id)}>
      <FileSvg />
      <span className="name">{title}<span className="ext">.md</span></span>
      <span className="dots" role="button" aria-label="menu"
        onClick={(e) => { e.stopPropagation(); openCtx({ type: "note", id: note.id, path: note.path, name: title }, e.currentTarget.getBoundingClientRect()); }}>⋮</span>
    </div>
  );
}

function Folder({ name, node, path }) {
  const { openCtx, setScoped } = useApp();
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState(false);
  const isRoot = path.indexOf("/") < 0;
  const folderNames = Object.keys(node.folders).sort((a, b) => a.localeCompare(b));
  const files = node.files.slice().sort((a, b) => (a.title || "").localeCompare(b.title || ""));
  return (
    <div className={"folder" + (open ? " open" : "")}>
      <div className={"row" + (sel ? " selected" : "")}
        onClick={() => { setOpen((o) => !o); setSel(true); setScoped({ notes: countNotes(node), links: countLinks(node) }); }}>
        <FolderSvg />
        <span className="name">{name}</span>
        {!isRoot && (
          <span className="dots" role="button" aria-label="menu"
            onClick={(e) => { e.stopPropagation(); openCtx({ type: "folder", path, name }, e.currentTarget.getBoundingClientRect()); }}>⋮</span>
        )}
      </div>
      <div className="children">
        {folderNames.map((f) => <Folder key={f} name={f} node={node.folders[f]} path={path + "/" + f} />)}
        {files.map((file) => <FileRow key={file.id} note={file} />)}
      </div>
    </div>
  );
}

export default function Browser({ hidden }) {
  const { state } = useApp();
  const notes = state.notes || [];
  const root = useMemo(() => buildTree(notes), [notes]);
  const rootFolders = Object.keys(root.folders).sort((a, b) => a.localeCompare(b));
  const empty = !rootFolders.length && !root.files.length;
  return (
    <div id="tree" className={"view" + (hidden ? " hidden" : "")}>
      {empty
        ? <div className="empty">No notes yet.<br />Send one to the bot to get started.</div>
        : (<>
            {rootFolders.map((f) => <Folder key={f} name={f} node={root.folders[f]} path={f} />)}
            {root.files.map((file) => <FileRow key={file.id} note={file} />)}
          </>)}
    </div>
  );
}
