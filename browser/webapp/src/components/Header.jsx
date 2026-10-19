import { useApp } from "../store/AppContext.jsx";
import CountRing from "./CountRing.jsx";
import FavoriteStories from "./FavoriteStories.jsx";

// The Inbox ring on the left, always available; a row of favourite folders that
// scrolls sideways beside it; and a folder-filter dots button on the right shown
// only on the Notes feed and the Map.
//
// The ring keeps its place and the row takes the slack, so the filter stays at
// the right edge however many folders there are.
//
// Sizes and stroke weights live in CSS — see styles.css.

export default function Header() {
  const { state, openFilter, openAddNote } = useApp();
  // Inbox is picked out by key rather than by position: the API decides root
  // order, and an order change should not hand the ring another root's count.
  const inbox = (state.stats || []).find((stat) => stat.key === "folder_inbox");
  const count = (inbox && inbox.count) || 0;
  const showFilter = state.view === "notes" || state.view === "map";
  return (
    <header>
      {/* Every viewBox here is cropped to the glyph's own bounds (plus half a
          stroke), so the CSS size is the size of the visible ink rather than of
          a box the path sits inside. See styles.css. */}
      <div className="hdr-side">
        {/* The rings and the number are a readout, not a control — only the
            badge is tappable. Two hit zones inside one circle is a mis-tap
            that opens a full-screen page. */}
        <div className="hdr-inbox">
          <CountRing count={count} />
          <button className="hdr-add" aria-label={`Add note (${count} in Inbox)`} onClick={() => openAddNote()}>
            <svg viewBox="-0.82 -0.82 13.64 13.64" fill="none" stroke="currentColor" strokeLinecap="round">
              <path d="M6 0v12M0 6h12" />
            </svg>
          </button>
        </div>
      </div>

      <FavoriteStories groups={state.favorites || []} />

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
