import { useApp } from "../store/AppContext.jsx";

// Instagram-style stats (Notes / Links / Reminders) flanked by two actions:
// add-note on the left, always available, and a folder-filter funnel on the
// right shown only on the Notes feed and the Map.
//
// Three columns, not absolute positioning: the side columns share the space the
// stats leave over, so each button lands in the middle of the gap between the
// numbers and its screen edge whatever the counts widen to. The right column
// keeps its width when the filter is hidden, so the stats stay centred.
//
// Sizes and stroke weights live in CSS, derived from `.stat b` — see styles.css.
export default function Header() {
  const { state, openFilter, openAddNote } = useApp();
  const stats = state.stats || { notes: 0, links: 0, reminders: 0 };
  const s = state.scoped;   // folder-scoped counts when an explorer folder is selected
  const statNotes = s ? s.notes : stats.notes;
  const statLinks = s ? s.links : stats.links;
  const showFilter = state.view === "notes" || state.view === "map";
  return (
    <header>
      <div className="hdr-side">
        <button className="hdr-add" aria-label="Add note" onClick={openAddNote}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round">
            <path d="M12 6v12M6 12h12" />
          </svg>
        </button>
      </div>

      <div className="hdr-stats">
        <div className="stat"><b>{statNotes}</b><span>Notes</span></div>
        <div className="stat"><b>{statLinks}</b><span>Links</span></div>
        <div className="stat"><b>{stats.reminders}</b><span>Reminders</span></div>
      </div>

      <div className="hdr-side">
        <button
          className={"hdr-filter" + (state.filterSel ? " active" : "") + (showFilter ? "" : " hidden")}
          aria-label="Filter folders"
          onClick={openFilter}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 5h18l-7 8v6l-4-2v-4z" />
          </svg>
        </button>
      </div>
    </header>
  );
}
