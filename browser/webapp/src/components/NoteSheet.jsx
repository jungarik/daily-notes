import { useEffect, useState } from "react";
import { useApp } from "../store/AppContext.jsx";
import { fetchNote } from "../lib/api.js";
import NoteCard from "./NoteCard.jsx";

// Bottom-sheet note preview — opened from the feed/explorer/search/graph and from
// a linked-note chip. Renders the same NoteCard template.
export default function NoteSheet() {
  const { state, closeNote } = useApp();
  const id = state.sheetNoteId;
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    if (id == null) { setDetail(null); return; }
    setLoading(true); setDetail(null);
    fetchNote(id).then((d) => { if (alive) { setDetail(d); setLoading(false); } });
    return () => { alive = false; };
  }, [id]);

  const open = id != null;
  return (
    <>
      <div className={"sheet-backdrop" + (open ? " show" : "")} onClick={closeNote} />
      <div className={"sheet" + (open ? " show" : "")}>
        <div className="grip" />
        <div id="sheetCard">
          {open && loading && <div className="empty">Loading…</div>}
          {open && !loading && !detail && <div className="empty">Preview unavailable.</div>}
          {detail && <NoteCard detail={detail} />}
        </div>
      </div>
    </>
  );
}
