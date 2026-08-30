import { useEffect, useRef, useState } from "react";
import { useApp } from "../store/AppContext.jsx";
import * as api from "../lib/api.js";

// Server-side search (/api/search): debounced query, tap a hit to open the note.
export default function Search({ hidden }) {
  const { state, openNote } = useApp();
  const q = (state.searchQuery || "").trim();
  const [hits, setHits] = useState([]);
  const reqRef = useRef(0);   // guards against out-of-order responses

  useEffect(() => {
    if (!q) { setHits([]); return; }
    const req = ++reqRef.current;
    const t = setTimeout(async () => {
      const res = await api.searchNotes(q);
      if (req === reqRef.current) setHits(res || []);
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  return (
    <div id="search" className={"view" + (hidden ? " hidden" : "")}>
      <div id="searchResults">
        {q && !hits.length && <div className="empty">No matches.</div>}
        {hits.map((n) => (
          <div className="row file" key={n.id} onClick={() => openNote(n.id)}>
            <span className="name">{(n.title && n.title.trim()) || "untitled"}<span className="ext">.md</span></span>
          </div>
        ))}
      </div>
    </div>
  );
}
