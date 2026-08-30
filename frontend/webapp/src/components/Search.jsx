import { useApp } from "../store/AppContext.jsx";

// Client-side filter over the loaded notes (title + path); tap to open the note.
export default function Search({ hidden }) {
  const { state, openNote } = useApp();
  const q = (state.searchQuery || "").trim().toLowerCase();
  const notes = state.notes || [];
  const hits = q
    ? notes.filter((n) => ((n.title || "") + " " + (n.path || "")).toLowerCase().includes(q)).slice(0, 50)
    : [];
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
