import { useEffect, useMemo, useRef, useState } from "react";
import {
  WHEEL_HEIGHT,
  WHEEL_ITEM_HEIGHT,
  ellipsisPath,
  wheelIndexAt,
  wheelItem,
  wheelOffset,
} from "../lib/format.js";
import { listAddNotePaths } from "../lib/api.js";

// The path wheel: the Add-note page's folder picker, anchored to its button.
//
// A drum rather than a dropdown. The column is pinned to the screen's right
// edge, so a menu has only one direction to grow — leftward — and a plain list
// there reads as a panel that happened to land beside a circle. Curving it on
// a wheel whose centre *is* the button makes the two one object: the items
// nearest the button are nearest the user, and the ones furthest along the arc
// turn away and vanish. `lib/format.wheelItem` is that arc, and the fade is
// the circle's own equation rather than a linear ramp.
//
// The glass is the same recipe as `.fab` and `.tabbar` — same tint, same blur,
// same hairline — because this is the floating-bar material, not a new one.
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

  const options = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const all = needle
      ? paths.filter((path) => path.toLowerCase().includes(needle))
      : paths;

    return all;
  }, [paths, query]);

  // Open centred on the note's own path — or on the default destination when
  // it has none, so the wheel starts where the note would actually go.
  useEffect(() => {
    const track = trackRef.current;
    if (!track || !options.length) return;
    const target = value || defaultPath;
    const index = Math.max(0, options.indexOf(target));

    track.scrollTop = index * WHEEL_ITEM_HEIGHT;
    setScrollTop(track.scrollTop);
  }, [options, value, defaultPath]);

  const typed = query.trim();
  // Text matching nothing is a new path, offered as its own row rather than a
  // mode to switch into — the same bargain the ⋮ menu's combobox strikes.
  const isNew = typed !== "" && !paths.some((path) => path === typed);

  return (
    <div className="path-wheel" ref={panelRef}>
      <input
        className="path-wheel-input"
        type="text"
        value={query}
        placeholder="Filter or type a new path…"
        autoComplete="off"
        autoCapitalize="off"
        spellCheck={false}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && typed) onPick(typed); }}
      />

      {isNew && (
        <button className="path-wheel-new" onClick={() => onPick(typed)}>
          {"Use “" + ellipsisPath(typed, 18) + "”"}
        </button>
      )}

      <div
        className="path-wheel-track"
        ref={trackRef}
        style={{ height: WHEEL_HEIGHT }}
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
      >
        {/* Half the wheel's height of padding at each end, so the first and
            last option can both reach the centre. */}
        <div style={{ height: WHEEL_HEIGHT / 2 - WHEEL_ITEM_HEIGHT / 2 }} />

        {options.map((path, index) => {
          const { x, scale, opacity } = wheelItem(wheelOffset(index, scrollTop));

          return (
            <button
              key={path}
              className={"path-wheel-opt" + (path === value ? " on" : "")}
              style={{
                height: WHEEL_ITEM_HEIGHT,
                transform: `translateX(${-x}px) scale(${scale})`,
                opacity,
                // An item past the rim is invisible; letting it keep its hit
                // zone would make the wheel's dead space tappable.
                pointerEvents: opacity < 0.15 ? "none" : "auto",
              }}
              onClick={() => onPick(path)}
            >
              {ellipsisPath(path)}
            </button>
          );
        })}

        <div style={{ height: WHEEL_HEIGHT / 2 - WHEEL_ITEM_HEIGHT / 2 }} />
      </div>

      {!options.length && !isNew && (
        <div className="path-wheel-empty">No folders yet.</div>
      )}
    </div>
  );
}

// Exported for the page's aria label and for tests: which option a snap has
// settled on, given the scroll position.
export const centredPath = (options, scrollTop) =>
  options[wheelIndexAt(scrollTop)] || "";
