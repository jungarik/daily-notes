import { formatCount, ringDashes } from "../lib/format.js";

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

// A bordered disc holding a count, with a dashed ring around it carrying one
// dash per note. Drawn in a fixed viewBox and sized by CSS, so the same drawing
// serves the Inbox at 64px and the favourite folders a little smaller: the
// number scales with it because it is SVG text in the same coordinates.
//
// A readout, never a control — whatever is tappable sits over it.
export default function CountRing({ count }) {
  const ring = ringDashes(count, RING_C, RING_STROKE);

  return (
    <svg className="hdr-ring" viewBox={`0 0 ${BOX} ${BOX}`} aria-hidden="true">
      {/* The circle itself: always drawn, so an empty count still has the
          bordered disc the number sits in. */}
      <circle
        className="hdr-ring-disc"
        cx={CENTER} cy={CENTER} r={DISC_R}
        fill="none" strokeWidth={DISC_STROKE}
      />
      {/* One dash per note, outside the disc. Omitted entirely at zero rather
          than drawn with an empty dash array: a circle with no dashes is a solid
          ring, which is the opposite reading. */}
      {ring.segments > 0 && (
        <circle
          className="hdr-ring-dashes"
          cx={CENTER} cy={CENTER} r={RING_R}
          fill="none" strokeWidth={RING_STROKE}
          strokeLinecap="round"
          strokeDasharray={`${ring.dash} ${ring.gap}`}
        />
      )}
      {/* The count lives inside the SVG, not in a positioned <span> over it, so
          it shares the circles' coordinate system: x/y ARE cx/cy, and no
          amount of inherited line-height or stacking can drift it off the
          centre the rings are drawn around.

          `dy` does the vertical centring rather than `dominant-baseline`, which
          older WebKit ignores. Digits have no descenders, so dropping the
          baseline by 0.35em puts the middle of the glyph on the middle of the
          circle. */}
      <text
        className="hdr-ring-count"
        x={CENTER} y={CENTER} dy="0.35em"
        textAnchor="middle"
      >
        {formatCount(count)}
      </text>
    </svg>
  );
}
