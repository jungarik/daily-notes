import { useEffect, useRef, useState, useCallback } from "react";
import { useApp } from "../store/AppContext.jsx";
import { createGraphEngine } from "../graph/engine.js";

// Connections map: a canvas force-directed graph with semantic zoom, a focused
// node card (Neighbors / Open note / Outline), and depth-1 ego subgraphs. The
// engine owns the canvas; this component owns the overlay UI and lifecycle.
export default function MapView({ hidden }) {
  const { state, openNote, setView } = useApp();
  const filterSel = state.filterSel;

  const canvasRef = useRef(null);
  const engineRef = useRef(null);
  const filterRef = useRef(filterSel);
  filterRef.current = filterSel;

  const [focus, setFocus] = useState(null);   // { id, title, path, links } or null
  const [meta, setMeta] = useState("");
  const [ego, setEgo] = useState(false);

  // Create the engine once, on the canvas element.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const engine = createGraphEngine(canvas, {
      getFilter: () => filterRef.current,
      onFocus: (node) => setFocus(node),
    });
    engineRef.current = engine;
    return () => { engine.destroy(); engineRef.current = null; };
  }, []);

  // Run the physics/render loop only while the Map tab is visible.
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine) return;
    if (!hidden) engine.start();
    else { engine.stop(); setFocus(null); setEgo(false); }
  }, [hidden]);

  // Rebuild when the shared folder filter changes (only matters while visible).
  useEffect(() => {
    if (hidden) return;
    engineRef.current && engineRef.current.syncFilter();
  }, [filterSel, hidden]);

  // Lazily enrich the focus card with tags + a snippet from the note detail.
  useEffect(() => {
    if (!focus) { setMeta(""); return; }
    setMeta((focus.links || 0) + " linked note(s)");
    let alive = true;
    engineRef.current && engineRef.current.loadDetail(focus.id).then((d) => {
      if (!alive || !d) return;
      const bits = [];
      if (d.tags && d.tags.length) bits.push("🏷 " + d.tags.join(", "));
      const snip = (d.text || "").trim().replace(/\s+/g, " ");
      if (snip) bits.push(snip.slice(0, 80) + (snip.length > 80 ? "…" : ""));
      if (bits.length) setMeta(bits.join("  ·  "));
    });
    return () => { alive = false; };
  }, [focus]);

  const onNeighbors = useCallback(() => {
    if (engineRef.current && engineRef.current.enterEgo()) setEgo(true);
  }, []);
  const onExitEgo = useCallback(() => {
    if (engineRef.current && engineRef.current.exitEgo()) setEgo(false);
  }, []);
  const onOpen = useCallback(() => { if (focus) openNote(focus.id); }, [focus, openNote]);

  // Outline: jump to the Explorer tab and flash the note's row. (Ancestor folders
  // stay collapsed — folder open-state is local to the Explorer tree.)
  const onOutline = useCallback(() => {
    if (!focus) return;
    setView("explorer");
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const row = document.querySelector('#tree [data-id="' + focus.id + '"]');
      if (!row) return;
      row.scrollIntoView({ block: "center", behavior: "smooth" });
      row.classList.add("flash");
      setTimeout(() => row.classList.remove("flash"), 1500);
    }));
  }, [focus, setView]);

  return (
    <div id="map" className={"view" + (hidden ? " hidden" : "")}>
      <canvas id="graph" ref={canvasRef} />
      <div className="map-hint">Pinch / scroll to zoom · drag to pan · tap a node</div>
      {ego && (
        <button id="egoReset" className="ego-reset" onClick={onExitEgo}>Full graph</button>
      )}
      {focus && (
        <div id="focusCard" className="focus-card">
          <button id="focusClose" className="focus-close" onClick={() => setFocus(null)}>✕</button>
          <div id="focusTitle" className="focus-title">{focus.title}</div>
          <div id="focusPath" className="focus-path">{"📁 " + focus.path}</div>
          <div id="focusMeta" className="focus-meta">{meta}</div>
          <div className="focus-actions">
            <button id="focusNeighbors" className="focus-btn" onClick={onNeighbors}>Neighbors</button>
            <button id="focusOpen" className="focus-btn" onClick={onOpen}>Open note</button>
            <button id="focusOutline" className="focus-btn" onClick={onOutline}>Outline</button>
          </div>
        </div>
      )}
    </div>
  );
}
