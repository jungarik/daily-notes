import { useApp } from "../store/AppContext.jsx";

// Instagram-style stats (Notes / Links / Reminders) + a folder-filter funnel
// shown only on the Notes feed and the Map.
export default function Header() {
  const { state, openFilter } = useApp();
  const notes = state.notes || [];
  const s = state.scoped;   // folder-scoped counts when a browser folder is selected
  const statNotes = s ? s.notes : notes.length;
  const statLinks = s ? s.links : Math.round(notes.reduce((a, n) => a + (n.links || 0), 0) / 2);
  const showFilter = state.view === "notes" || state.view === "map";
  return (
    <header>
      <div className="stat"><b>{statNotes}</b><span>Notes</span></div>
      <div className="stat"><b>{statLinks}</b><span>Links</span></div>
      <div className="stat"><b>{state.reminderCount}</b><span>Reminders</span></div>
      <button
        className={"hdr-filter" + (state.filterSel ? " active" : "") + (showFilter ? "" : " hidden")}
        aria-label="Filter folders"
        onClick={openFilter}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 5h18l-7 8v6l-4-2v-4z" />
        </svg>
      </button>
    </header>
  );
}
