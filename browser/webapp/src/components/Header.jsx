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
  // The API returns every reported root in display order and already localised;
  // the header has room for three, so it takes the first three rather than
  // naming them again here and inviting the two lists to drift.
  const stats = (state.stats || []).slice(0, 3);
  const showFilter = state.view === "notes" || state.view === "map";
  return (
    <header>
      {/* Every viewBox here is cropped to the glyph's own bounds (plus half a
          stroke), so the CSS size is the size of the visible ink rather than of
          a box the path sits inside. See styles.css. */}
      <div className="hdr-side">
        <button className="hdr-add" aria-label="Add note" onClick={openAddNote}>
          <svg viewBox="-0.82 -0.82 13.64 13.64" fill="none" stroke="currentColor" strokeLinecap="round">
            <path d="M6 0v12M0 6h12" />
          </svg>
        </button>
      </div>

      <div className="hdr-stats">
        {stats.map((stat) => (
          <div className="stat" key={stat.key}>
            <b>{stat.count}</b><span>{stat.label}</span>
          </div>
        ))}
      </div>

      <div className="hdr-side">
        <button
          className={"hdr-filter" + (state.filterSel ? " active" : "") + (showFilter ? "" : " hidden")}
          aria-label="Filter folders"
          onClick={openFilter}
        >
          {/* Three stacked dots, filled rather than stroked. The box is the
              ink: equal dots and gaps fill all 10 units, so the CSS height is
              the distance from the top of the first dot to the bottom of the
              last. */}
          <svg viewBox="0 0 2 10" fill="currentColor">
            <circle cx="1" cy="1" r="1" />
            <circle cx="1" cy="5" r="1" />
            <circle cx="1" cy="9" r="1" />
          </svg>
        </button>
      </div>
    </header>
  );
}
