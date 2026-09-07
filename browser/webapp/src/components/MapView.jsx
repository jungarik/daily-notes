import { useEffect, useRef, useState, useCallback } from "react";
import { useApp } from "../store/AppContext.jsx";
import { createGraphEngine } from "../graph/engine.js";
import NoteMiniCard from "./NoteMiniCard.jsx";
import { pathColor } from "../lib/format.js";

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
  const [cards, setCards] = useState([]);    // the nodes currently carrying a card

  // Card DOM nodes, positioned imperatively from the engine's animation frame so
  // panning/zooming never re-renders React.
  const cardEls = useRef(new Map());
  const cardPos = useRef(new Map());
  const place = (el, at) => {
    el.style.transform = "translate3d(" + at.x + "px," + at.y + "px,0)";
  };
  const setCardEl = useCallback((id, el) => {
    if (!el) { cardEls.current.delete(id); return; }
    cardEls.current.set(id, el);
    const at = cardPos.current.get(id);

    if (at) place(el, at);
  }, []);

  // Create the engine once, on the canvas element.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const engine = createGraphEngine(canvas, {
      getFilter: () => filterRef.current,
      onFocus: (node) => setFocus(node),
      onCards: (nodes) => setCards(nodes),
      onLayout: (layout) => {
        for (const card of layout) {
          cardPos.current.set(card.id, card);
          const el = cardEls.current.get(card.id);
          if (el) place(el, card);
        }
      },
    });
    engineRef.current = engine;
    return () => { engine.destroy(); engineRef.current = null; };
  }, []);

  // Run the physics/render loop only while the Map tab is visible.
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine) return;
    if (!hidden) engine.start();
    else { engine.stop(); setFocus(null); setEgo(false); setCards([]); }
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
      {/* The engine hands the nodes over most-linked first; that order becomes a
          descending z-index, so the busiest note sits on top of the heap and the
          focused one is lifted above everything. */}
      <div className="map-cards" aria-hidden="true">
        {cards.map((n, i) => (
          <div key={n.id} ref={(el) => setCardEl(n.id, el)}
            style={{
              zIndex: focus && focus.id === n.id ? cards.length + 1 : cards.length - i,
              "--card-accent": pathColor(n.path),
            }}
            className={"map-card" + (focus && focus.id === n.id ? " sel" : "")}>
            <NoteMiniCard id={n.id} note={{
              title: n.title,
              path: n.path,
              date: n.created_at,
              links: n.degree,
              attachments: n.attachments,
            }} />
          </div>
        ))}
      </div>
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
