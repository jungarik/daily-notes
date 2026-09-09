import { useEffect, useRef, useState, useCallback } from "react";
import { useApp } from "../store/AppContext.jsx";
import { createGraphEngine } from "../graph/engine.js";
import NoteMiniCard from "./NoteMiniCard.jsx";
import { pathColor } from "../lib/format.js";

// Connections map: the vault as a globe. Notes are laid out on the sphere;
// dragging rolls it under the finger, two fingers scale it, and the folder
// filter decides what is on it. Tapping a note turns it to the front, holding
// one opens it. The engine owns the canvas and every per-frame style; this
// component owns the card list and the lifecycle.
export default function MapView({ hidden }) {
  const { state, openNote } = useApp();
  const filterSel = state.filterSel;

  const canvasRef = useRef(null);
  const engineRef = useRef(null);
  const filterRef = useRef(filterSel);
  filterRef.current = filterSel;

  const [cards, setCards] = useState([]);    // the nodes currently carrying a card

  // Card DOM nodes, positioned imperatively from the engine's animation frame so
  // panning/zooming never re-renders React.
  const cardEls = useRef(new Map());
  const cardPos = useRef(new Map());
  // Position, foreshortening, fade, blur and the held-note marker all come from
  // the engine's per-frame layout — it eases the focus transition itself, so none
  // of this is a CSS transition. The card scales from its top-left, which is
  // where the engine puts it.
  const place = (el, at) => {
    el.style.transform = "translate3d(" + at.x + "px," + at.y + "px,0) scale(" + at.k + ")";
    el.style.opacity = at.alpha;
    el.style.filter = at.blur > 0.05 ? "blur(" + at.blur.toFixed(2) + "px)" : "none";
    el.classList.toggle("sel", !!at.marked);
  };
  const setCardEl = useCallback((id, el) => {
    if (!el) { cardEls.current.delete(id); return; }
    cardEls.current.set(id, el);
    const at = cardPos.current.get(id);

    if (at) place(el, at);
  }, []);

  // openNote lands in a ref so the engine can be created once and still call the
  // current handler.
  const openRef = useRef(openNote);
  openRef.current = openNote;

  // Create the engine once, on the canvas element.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const engine = createGraphEngine(canvas, {
      getFilter: () => filterRef.current,
      onOpenNote: (id) => openRef.current(id),
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
    else { engine.stop(); setCards([]); }
  }, [hidden]);

  // Rebuild when the shared folder filter changes (only matters while visible).
  useEffect(() => {
    if (hidden) return;
    engineRef.current && engineRef.current.syncFilter();
  }, [filterSel, hidden]);

  return (
    <div id="map" className={"view" + (hidden ? " hidden" : "")}>
      <canvas id="graph" ref={canvasRef} />
      {/* The engine hands the nodes over front-to-back — nearest depth first, then
          most-linked — and that order becomes a descending z-index. A tapped note
          is depth 0, so it leads the pile without needing any highlight. */}
      <div className="map-cards" aria-hidden="true">
        {cards.map((n, i) => (
          <div key={n.id} ref={(el) => setCardEl(n.id, el)}
            style={{ zIndex: cards.length - i, "--card-accent": pathColor(n.path) }}
            className="map-card">
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
      <div className="map-hint">Roll · pinch to scale · tap a note · hold to open</div>
    </div>
  );
}
