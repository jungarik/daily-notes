import { useMemo } from "react";
import { useApp } from "../store/AppContext.jsx";
import { notePathKey } from "../lib/format.js";

// Tri-state folder filter over the feed's paths; applies to the feed (and the
// Map). Selection persists in the store (localStorage-backed).
export default function FolderFilter() {
  const { state, closeFilter, setFilter } = useApp();
  const { filterOpen, feed, filterSel } = state;

  const keys = useMemo(
    () => (feed ? [...new Set(feed.map(notePathKey))].filter(Boolean).sort() : []),
    [feed]
  );

  const rows = useMemo(() => {
    const root = { children: new Map() };
    for (const key of keys) {
      let node = root, acc = "";
      for (const seg of key.split("/")) {
        acc = acc ? acc + "/" + seg : seg;
        if (!node.children.has(seg)) node.children.set(seg, { name: seg, path: acc, children: new Map() });
        node = node.children.get(seg);
      }
    }
    const out = [];
    (function walk(node, depth) {
      for (const child of [...node.children.values()].sort((a, b) => a.name.localeCompare(b.name))) {
        out.push({ name: child.name, path: child.path, depth });
        walk(child, depth + 1);
      }
    })(root, 0);
    return out;
  }, [keys]);

  if (!filterOpen) return null;

  const sel = filterSel || new Set(keys);
  const descendant = (path) => keys.filter((k) => k === path || k.startsWith(path + "/"));
  const countUnder = (path) => (feed || []).filter((d) => { const k = notePathKey(d); return k === path || k.startsWith(path + "/"); }).length;

  const toggle = (path, checked) => {
    const dkeys = descendant(path);
    const next = filterSel ? new Set(filterSel) : new Set(keys);
    if (checked) dkeys.forEach((k) => next.add(k)); else dkeys.forEach((k) => next.delete(k));
    setFilter(next.size >= keys.length ? null : next);   // everything selected = no filter
  };

  return (
    <>
      <div className="sheet-backdrop show" onClick={closeFilter} />
      <div className="sheet show" id="filterSheet">
        <div className="grip" />
        <div className="filter-head">
          <div className="card-title">Filter folders</div>
          <div className="filter-quick">
            <button className="filter-link" onClick={() => setFilter(null)}>All</button>
            <button className="filter-link" onClick={() => setFilter(new Set())}>Clear</button>
          </div>
        </div>
        <div className="filter-tree">
          {!keys.length ? (
            <div className="empty">No folders yet.</div>
          ) : (
            rows.map((r) => {
              const dkeys = descendant(r.path);
              const selN = dkeys.filter((k) => sel.has(k)).length;
              const checked = selN === dkeys.length;
              const indet = selN > 0 && selN < dkeys.length;
              return (
                <label className="filter-row" key={r.path} style={{ paddingLeft: 4 + r.depth * 18 + "px" }}>
                  <input type="checkbox" checked={checked}
                    ref={(el) => { if (el) el.indeterminate = indet; }}
                    onChange={(e) => toggle(r.path, e.target.checked)} />
                  <span className="filter-name">{r.name}</span>
                  <span className="filter-count">{countUnder(r.path)}</span>
                </label>
              );
            })
          )}
        </div>
        <div className="path-actions">
          <button className="path-btn primary" onClick={closeFilter}>Done</button>
        </div>
      </div>
    </>
  );
}
