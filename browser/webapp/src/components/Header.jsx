import { useApp } from "../store/AppContext.jsx";
import { formatCount, ringDashes } from "../lib/format.js";

// Root-folder counts flanked by two actions: the Inbox ring on the left, always
// available, and a folder-filter funnel on the right shown only on the Notes
// feed and the Map.
//
// Three columns, not absolute positioning: the side columns share the space the
// stats leave over, so each button lands in the middle of the gap between the
// numbers and its screen edge whatever the counts widen to. The right column
// keeps its width when the filter is hidden, so the stats stay centred.
//
// Sizes and stroke weights live in CSS, derived from `.stat b` — see styles.css.

// Two concentric rings in a 64-unit viewBox, here rather than in CSS because
// the dash pattern is computed from them.
//
// The inner one is the circle that was always there: 54 units across, the size
// the dock's buttons use, holding the count. The dashed one is genuinely
// additional — it appears outside that circle only when the Inbox has
// something in it, so an empty Inbox is the plain bordered circle and nothing
// else. Each radius is inset by half its own stroke, so the ink lands inside
// the band rather than straddling its edge.
const DISC_SIZE = 54;
const DISC_STROKE = 1.5;
const DISC_R = (DISC_SIZE - DISC_STROKE) / 2;

// The clear space between the two bands. Below about 2 units they read as one
// thick ring rather than as a circle with something around it.
const RING_INSET = 2.5;
const RING_STROKE = 2.5;

// Each value falls out of the one before it, so moving the disc or widening a
// stroke keeps the gap — and the box stays exactly big enough for the outer
// ink, with no invented padding to keep in sync.
const RING_R = DISC_R + DISC_STROKE / 2 + RING_INSET + RING_STROKE / 2;
const RING_C = 2 * Math.PI * RING_R;
const BOX = 2 * (RING_R + RING_STROKE / 2);
const CENTER = BOX / 2;

export default function Header() {
  const { state, openFilter, openAddNote } = useApp();
  const all = state.stats || [];
  // The Inbox count moved into the ring, so the stats row shows the roots after
  // it — Projects / Areas / Resources. Selected by key rather than by slicing
  // off the front: the API decides root order, and an order change here should
  // move the columns, not silently drop the wrong one.
  const inbox = all.find((stat) => stat.key === "folder_inbox");
  const stats = all.filter((stat) => stat.key !== "folder_inbox").slice(0, 3);
  const count = (inbox && inbox.count) || 0;
  const ring = ringDashes(count, RING_C, RING_STROKE);
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
          <svg className="hdr-ring" viewBox={`0 0 ${BOX} ${BOX}`} aria-hidden="true">
            {/* The circle itself: always drawn, so an empty Inbox still has
                the bordered disc the count sits in. */}
            <circle
              className="hdr-ring-disc"
              cx={CENTER} cy={CENTER} r={DISC_R}
              fill="none" strokeWidth={DISC_STROKE}
            />
            {/* One dash per waiting note, outside the disc. Omitted entirely
                at zero rather than drawn with an empty dash array: a circle
                with no dashes is a solid ring, which is the opposite reading. */}
            {ring.segments > 0 && (
              <circle
                className="hdr-ring-dashes"
                cx={CENTER} cy={CENTER} r={RING_R}
                fill="none" strokeWidth={RING_STROKE}
                strokeLinecap="round"
                strokeDasharray={`${ring.dash} ${ring.gap}`}
              />
            )}
            {/* The count lives inside the SVG, not in a positioned <span> over
                it, so it shares the circles' coordinate system: x/y ARE cx/cy,
                and no amount of inherited line-height or stacking can drift it
                off the centre the rings are drawn around.

                `dy` does the vertical centring rather than `dominant-baseline`,
                which older WebKit ignores. Digits have no descenders, so
                dropping the baseline by 0.35em puts the middle of the glyph on
                the middle of the circle. */}
            <text
              className="hdr-ring-count"
              x={CENTER} y={CENTER} dy="0.35em"
              textAnchor="middle"
            >
              {formatCount(count)}
            </text>
          </svg>
          <button className="hdr-add" aria-label={`Add note (${count} in Inbox)`} onClick={() => openAddNote()}>
            <svg viewBox="-0.82 -0.82 13.64 13.64" fill="none" stroke="currentColor" strokeLinecap="round">
              <path d="M6 0v12M0 6h12" />
            </svg>
          </button>
        </div>
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
