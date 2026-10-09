import { useEffect, useMemo, useRef, useState } from "react";
import {
  WHEEL_HEIGHT,
  WHEEL_ITEM_HEIGHT,
  pathColor,
  wheelItem,
  wheelOffset,
} from "../lib/format.js";

// The path wheel: the Add-note page's folder pickers, anchored to their buttons.
// There are two — the root folder and the sub-folder under it — and this one
// component serves both. The caller supplies `load` (the fetch, resolving to
// `{items, initial}`) and `allowNew` (only the sub-folder wheel accepts a name
// that isn't listed: the server rejects an unknown root, so offering to type
// one would only lead to a 422).
//
// There is no panel. The options scroll in a transparent column beside the
// button — a container would have been a second floating object competing with
// the bar it hangs off, and the page is already glass over the note's text. So
// the rows are the whole UI: raised pills, each carrying its folder's own hue,
// bowing along a circle whose centre is the button (`lib/format.wheelItem`) and
// fading with the circle's own equation, so the column reads as attached to the
// control rather than parked next to it. A gradient mask on the track fades
// both ends as well — the arc fade follows a row as the wheel turns away from
// you, the mask is pinned to the visible edge, and it takes both for the two
// boundaries to look alike.
//
// The filter is the first row, not a header above the list: the same pill as
// every option, so "type something new" is an option rather than a mode, and
// it fades with the rest.
export default function PathWheel({
  value,
  load,
  allowNew = false,
  colorPrefix = "",
  placeholder,
  onPick,
  onClose,
}) {
  const [items, setItems] = useState([]);
  // Where an unpicked note goes, as the API reports it. Named for the
  // destination rather than for a "root": the client once invented a folder
  // label for notes that had no path, that feature is retired, and
  // `tests/test_vault_visibility.py` keeps its name out of this directory so
  // nobody reads this as it coming back.
  const [defaultPath, setDefaultPath] = useState("");
  const [query, setQuery] = useState("");
  const [scrollTop, setScrollTop] = useState(0);
  const trackRef = useRef(null);
  const panelRef = useRef(null);

  // The wheel mounts each time it opens, so `load` runs once per open — it is
  // deliberately not a dependency: the caller's inline closure would refetch
  // on every render.
  useEffect(() => {
    let live = true;
    load().then((payload) => {
      if (!live) return;
      setItems(payload.items || []);
      setDefaultPath(payload.initial || "");
    });

    return () => { live = false; };
  }, []);

  // Dismiss on an outside tap, deferred so the opening tap doesn't close it —
  // the same trick, and the same reason, as the ⋮ menu's.
  useEffect(() => {
    const onDoc = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) onClose();
    };
    const id = setTimeout(() => document.addEventListener("click", onDoc), 0);

    return () => { clearTimeout(id); document.removeEventListener("click", onDoc); };
  }, [onClose]);

  const typed = query.trim();

  // Row 0 is always the filter. On a wheel that `allowNew`, a typed name that
  // matches nothing follows it as an ordinary option row — selecting it is how
  // you use it, so there is no separate "create" control to explain.
  const options = useMemo(() => {
    const needle = typed.toLowerCase();
    const matching = needle
      ? items.filter((item) => item.toLowerCase().includes(needle))
      : items;
    const isNew = allowNew && typed !== "" && !items.includes(typed);

    return isNew ? [typed, ...matching] : matching;
  }, [items, typed, allowNew]);

  // Open centred on the note's own folder — or on the default destination when
  // it has none, so the wheel starts where the note would actually go. The
  // filter's row offsets every option by one.
  useEffect(() => {
    const track = trackRef.current;
    if (!track || !options.length) return;
    const found = options.indexOf(value || defaultPath);

    track.scrollTop = (found < 0 ? 0 : found + 1) * WHEEL_ITEM_HEIGHT;
    setScrollTop(track.scrollTop);
  }, [options, value, defaultPath]);

  const row = (index) => {
    const { x, scale, opacity } = wheelItem(wheelOffset(index, scrollTop));

    return {
      // No height here: `.path-wheel-opt` owns it (44px pill + 6px margins =
      // the 56px row pitch `WHEEL_ITEM_HEIGHT` assumes, which
      // `tests/test_path_wheel.py` checks adds up). Setting it inline would
      // mean an `!important` in the stylesheet to win it back.
      transform: `translateX(${-x}px) scale(${scale})`,
      opacity,
      // A row past the rim is invisible; letting it keep its hit zone would
      // make the wheel's dead space tappable.
      pointerEvents: opacity < 0.15 ? "none" : "auto",
    };
  };

  return (
    <div className="path-wheel" ref={panelRef}>
      <div
        className="path-wheel-track"
        ref={trackRef}
        style={{ height: WHEEL_HEIGHT }}
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
      >
        {/* Half the wheel's height of padding at each end, so the first and
            last row can both reach the centre. */}
        <div style={{ height: WHEEL_HEIGHT / 2 - WHEEL_ITEM_HEIGHT / 2 }} />

        {/* No opacity floor, and no exemption from the arc. It had one, so it
            could not be missed — but as the topmost row that made the top of
            the wheel the one edge where nothing ever disappeared, which read
            as a broken fade rather than as a helpful control. It is findable
            the way every other row is: by scrolling to it. */}
        <div className="path-wheel-opt filter" style={row(0)}>
          <input
            type="text"
            value={query}
            placeholder={placeholder}
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            // A folder name has no slash: it would be a second level hiding in
            // the first, so it is dropped as it is typed.
            onChange={(e) => setQuery(e.target.value.replace(/[\\/]/g, ""))}
            onKeyDown={(e) => {
              if (e.key === "Enter" && typed && (allowNew || items.includes(typed))) onPick(typed);
            }}
          />
        </div>

        {options.map((item, index) => (
          <button
            key={item}
            className={"path-wheel-opt" + (item === value ? " on" : "")}
            style={row(index + 1)}
            onClick={() => onPick(item)}
          >
            {/* `direction: rtl` on the label puts the overflow — and the
                ellipsis — on the *left*, so a long path keeps its leaf (the
                part that distinguishes two folders under one root) and loses
                its stem. `<bdi>` isolates the text so the bidi algorithm
                still lays "Projects/api" out left to right inside it; without
                it the slashes are neutral characters and migrate. */}
            {/* The folder's own colour, the same stable hue
                `lib/format.pathColor` gives the map's dots and node cards. It
                is the app's existing word for "which folder", and it gives a
                column of otherwise identical rows something to recognise at a
                glance — without inventing a palette. */}
            <i className="path-wheel-dot" style={{ background: pathColor(colorPrefix + item) }} />
            <span className="path-wheel-label"><bdi>{item}</bdi></span>
          </button>
        ))}

        <div style={{ height: WHEEL_HEIGHT / 2 - WHEEL_ITEM_HEIGHT / 2 }} />
      </div>
    </div>
  );
}
