import { useEffect, useMemo, useRef, useState } from "react";
import {
  WHEEL_HEIGHT,
  WHEEL_ITEM_HEIGHT,
  wheelItem,
  wheelOffset,
} from "../lib/format.js";
import { listAddNotePaths } from "../lib/api.js";

// The path wheel: the Add-note page's folder picker, anchored to its button.
//
// There is no panel. The options scroll in a transparent column beside the
// button — a container would have been a second floating object competing with
// the bar it hangs off, and the page is already glass over the note's text. So
// the rows are the whole UI: a flat dark tint, no blur, no shadow, no hairline.
// The only thing left of the old chrome is the arc: each row bows out along a
// circle whose centre is the button (`lib/format.wheelItem`) and fades with the
// circle's own equation, so the column reads as attached to the control rather
// than parked next to it.
//
// The filter is the first row, not a header above the list. It is the same pill
// as every option, so "type something new" is an option rather than a mode.
export default function PathWheel({ value, onPick, onClose }) {
  const [paths, setPaths] = useState([]);
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

  useEffect(() => {
    let live = true;
    listAddNotePaths().then((payload) => {
      if (!live) return;
      setPaths(payload.paths || []);
      setDefaultPath(payload.default_root || "");
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

  // Row 0 is always the filter. A typed path that matches nothing follows it
  // as an ordinary option row — selecting it is how you use it, so there is no
  // separate "create" control to explain.
  const options = useMemo(() => {
    const needle = typed.toLowerCase();
    const matching = needle
      ? paths.filter((path) => path.toLowerCase().includes(needle))
      : paths;
    const isNew = typed !== "" && !paths.includes(typed);

    return isNew ? [typed, ...matching] : matching;
  }, [paths, typed]);

  // Open centred on the note's own path — or on the default destination when
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

  const filterStyle = row(0);

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

        <div
          className="path-wheel-opt filter"
          style={{
            ...filterStyle,
            // The filter keeps a floor on both: faded to nothing at the rim it
            // would be a control the user cannot find, and one they cannot tap
            // is worse than one that is merely dim.
            opacity: Math.max(filterStyle.opacity, 0.45),
            pointerEvents: "auto",
          }}
        >
          <input
            type="text"
            value={query}
            placeholder="Filter or new path…"
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && typed) onPick(typed); }}
          />
        </div>

        {options.map((path, index) => (
          <button
            key={path}
            className={"path-wheel-opt" + (path === value ? " on" : "")}
            style={row(index + 1)}
            onClick={() => onPick(path)}
          >
            {/* `direction: rtl` on the label puts the overflow — and the
                ellipsis — on the *left*, so a long path keeps its leaf (the
                part that distinguishes two folders under one root) and loses
                its stem. `<bdi>` isolates the text so the bidi algorithm
                still lays "Projects/api" out left to right inside it; without
                it the slashes are neutral characters and migrate. */}
            <span className="path-wheel-label"><bdi>{path}</bdi></span>
          </button>
        ))}

        <div style={{ height: WHEEL_HEIGHT / 2 - WHEEL_ITEM_HEIGHT / 2 }} />
      </div>
    </div>
  );
}
