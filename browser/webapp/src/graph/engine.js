// Canvas force-directed graph engine (ported from the vanilla map.js).
// Framework-agnostic: the React MapView owns the focus card / ego-reset UI and
// drives this engine through callbacks. The engine owns the canvas, the physics
// sim, pan/zoom input, and depth-1 ego subgraphs.
//
// Nodes are drawn as a faint folder-coloured dot plus a note card. The cards are
// real DOM (the shared NoteMiniCard, so the map and the chat tab show the same
// card); this engine only decides which nodes get one and where it sits, and
// reports that through `onCards` (set changed) and `onLayout` (per-frame
// positions). Cards are fixed screen size, so zooming in spreads nodes apart and
// reveals more of them — the semantic zoom falls out of the overlap culling.
import { fetchGraph, fetchNote } from "../lib/api.js";
import { pathColor } from "../lib/format.js";
import { tg } from "../lib/telegram.js";

// Cards are fixed screen-size (they do not scale with zoom); the layout below
// places them in screen space and culls overlaps, so zooming changes density
// rather than card size.
const CARD_W = 200, CARD_H = 48, CARD_GAP = 6, MAX_CARDS = 60, EDGE = 40;

function clamp(v, lo, hi) { return hi < lo ? lo : Math.max(lo, Math.min(hi, v)); }

// A faint folder-coloured dot anchors every node; the card carries the detail.
function nodeRadius(n) { return 3 + Math.min(6, (n.degree || 0) * 0.8); }

function buildSim(data, W, H) {
  const spread = Math.min(W, H) * 0.5 || 200;
  const nodes = data.nodes.map((n) => ({ ...n, x: (Math.random() - .5) * spread, y: (Math.random() - .5) * spread, vx: 0, vy: 0 }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges = (data.edges || []).map((e) => ({ a: byId.get(e.source), b: byId.get(e.target) })).filter((e) => e.a && e.b);
  return { nodes, edges, alpha: 1 };
}

function stepSim(sim) {
  const nodes = sim.nodes, a = sim.alpha;
  const REPEL = 1600, SPRING = 0.02, LEN = 64, CENTER = 0.015, DAMP = 0.85;
  for (let i = 0; i < nodes.length; i++) {
    const ni = nodes[i];
    for (let j = i + 1; j < nodes.length; j++) {
      const nj = nodes[j];
      let dx = ni.x - nj.x, dy = ni.y - nj.y, d2 = dx * dx + dy * dy;
      if (d2 < 0.01) { dx = Math.random() - .5; dy = Math.random() - .5; d2 = dx * dx + dy * dy + 0.01; }
      const inv = 1 / Math.sqrt(d2), f = REPEL / d2, fx = dx * inv * f, fy = dy * inv * f;
      ni.vx += fx; ni.vy += fy; nj.vx -= fx; nj.vy -= fy;
    }
  }
  for (const e of sim.edges) {
    let dx = e.b.x - e.a.x, dy = e.b.y - e.a.y; const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
    const f = (d - LEN) * SPRING, fx = dx / d * f, fy = dy / d * f;
    e.a.vx += fx; e.a.vy += fy; e.b.vx -= fx; e.b.vy -= fy;
  }
  for (const n of nodes) {
    n.vx += -n.x * CENTER; n.vy += -n.y * CENTER;
    n.x += n.vx * a; n.y += n.vy * a;
    n.vx *= DAMP; n.vy *= DAMP;
  }
  sim.alpha = Math.max(0.03, a * 0.985);
}

// One engine instance per mounted canvas. All former GRAPH globals live on G.
export function createGraphEngine(canvas, opts) {
  const G = {
    canvas, ctx: canvas.getContext("2d"), dpr: 1, sim: null, raf: null,
    running: false, loaded: false, selected: null, focusNodeId: null,
    cards: [], cardSig: null,
    ego: null, focusReq: 0, data: null, filterSig: null,
    view: { scale: 1, tx: 0, ty: 0 },
  };
  const getFilter = opts.getFilter || (() => null);   // returns a Set of folder keys, or null = all
  const onFocus = opts.onFocus || (() => {});          // (node|null) → React renders the focus card
  const onCards = opts.onCards || (() => {});          // (nodes[]) → the visible card set changed
  const onLayout = opts.onLayout || (() => {});        // (cards[]) → per-frame screen positions

  function sizeCanvas() {
    const c = G.canvas; if (!c) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2); G.dpr = dpr;
    c.width = Math.round(c.clientWidth * dpr); c.height = Math.round(c.clientHeight * dpr);
  }

  function autoFit() {
    const { sim, canvas, view } = G; if (!sim || !sim.nodes.length) return;
    let a = 1e9, b = 1e9, c = -1e9, d = -1e9;
    for (const n of sim.nodes) { a = Math.min(a, n.x); c = Math.max(c, n.x); b = Math.min(b, n.y); d = Math.max(d, n.y); }
    const w = canvas.clientWidth, h = canvas.clientHeight, gw = Math.max(1, c - a), gh = Math.max(1, d - b);
    view.scale = Math.min(w / (gw + 120), h / (gh + 120), 2);
    view.tx = w / 2 - (a + c) / 2 * view.scale;
    view.ty = h / 2 - (b + d) / 2 * view.scale;
  }

  function drawGraph() {
    const { ctx, canvas, sim, view, dpr, selected } = G; if (!ctx || !sim) return;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.translate(view.tx, view.ty); ctx.scale(view.scale, view.scale);
    ctx.strokeStyle = "rgba(255,255,255,.12)"; ctx.lineWidth = 1 / view.scale;
    ctx.beginPath();
    for (const e of sim.edges) { ctx.moveTo(e.a.x, e.a.y); ctx.lineTo(e.b.x, e.b.y); }
    ctx.stroke();
    for (const n of sim.nodes) {
      ctx.beginPath(); ctx.arc(n.x, n.y, nodeRadius(n), 0, Math.PI * 2);
      ctx.fillStyle = pathColor(n.path); ctx.fill();
      if (selected === n.id) { ctx.lineWidth = 2 / view.scale; ctx.strokeStyle = "#fff"; ctx.stroke(); }
    }
    ctx.restore();
    layoutCards();
  }

  // Every node in view gets a card, and they are allowed to overlap: the result
  // is a heap where the most-linked notes sit on top, fully readable, and the
  // rest peek out from underneath. `cards` is ordered most-linked first, which
  // is both the stacking order (React maps it to a descending z-index) and the
  // hit-test order, so a tap always lands on the card you can actually see.
  function layoutCards() {
    const { sim, view, selected, canvas } = G;
    const s = view.scale;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    const cards = [];
    for (const n of [...sim.nodes].sort((x, y) => (y.degree || 0) - (x.degree || 0))) {
      if (cards.length >= MAX_CARDS) break;
      const sx = n.x * s + view.tx, sy = n.y * s + view.ty;

      if (sx < -EDGE || sx > w + EDGE || sy < -EDGE || sy > h + EDGE) continue;   // offscreen node

      // Cards keep their full width — an edge card is nudged back inside rather
      // than sliced off, since in a heap it is already offset from its dot.
      const x = clamp(sx - CARD_W / 2, 2, w - CARD_W - 2);
      const y = clamp(sy + nodeRadius(n) * s + CARD_GAP, 2, h - CARD_H - 2);
      cards.push({ id: n.id, x, y, node: n, selected: selected === n.id });
    }
    G.cards = cards;
    publishCards();
  }

  // Content changes are rare (a new visible set); positions change every frame.
  // Splitting them keeps React re-renders off the animation path.
  function publishCards() {
    const sig = G.cards.map((c) => c.id + (c.selected ? "*" : "")).join(",");

    if (sig !== G.cardSig) {
      G.cardSig = sig;
      onCards(G.cards.map((c) => c.node));
    }

    onLayout(G.cards);
  }

  function emptyMessage(msg) {
    const { ctx, canvas, dpr } = G;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
    ctx.fillStyle = "rgba(150,150,150,.85)"; ctx.font = "13px sans-serif"; ctx.textAlign = "center";
    ctx.fillText(msg, canvas.clientWidth / 2, canvas.clientHeight / 2); ctx.textAlign = "start";
  }

  function loop() {
    if (!G.running) return;
    stepSim(G.sim); drawGraph();
    G.raf = requestAnimationFrame(loop);
  }
  function startLoop() { if (G.running || !G.sim) return; G.running = true; G.raf = requestAnimationFrame(loop); }
  function stopLoop() { G.running = false; if (G.raf) cancelAnimationFrame(G.raf); G.raf = null; }

  function zoomAt(cx, cy, factor) {
    const v = G.view, gx = (cx - v.tx) / v.scale, gy = (cy - v.ty) / v.scale;
    v.scale = Math.max(0.2, Math.min(4, v.scale * factor));
    v.tx = cx - gx * v.scale; v.ty = cy - gy * v.scale;
  }

  function graphTap(clientX, clientY) {
    const c = G.canvas, rect = c.getBoundingClientRect(), v = G.view;
    const px = clientX - rect.left, py = clientY - rect.top;

    const hit = (card) => px >= card.x && px <= card.x + CARD_W
                       && py >= card.y && py <= card.y + CARD_H;
    const top = G.cards.find((c) => c.selected && hit(c)) || G.cards.find(hit);

    if (top) {
      focusNode(top.node);
      return;
    }

    const gx = (px - v.tx) / v.scale, gy = (py - v.ty) / v.scale;
    let best = null, bestd = 1e9;
    for (const n of (G.sim ? G.sim.nodes : [])) {
      const r = nodeRadius(n) + 10, dx = n.x - gx, dy = n.y - gy, d = dx * dx + dy * dy;
      if (d < r * r && d < bestd) { best = n; bestd = d; }
    }
    if (best) focusNode(best); else clearFocus();
  }

  function neighborCount(id) {
    const edges = (G.data && G.data.edges) || [];
    let n = 0;
    for (const e of edges) if (e.source === id || e.target === id) n++;
    return n;
  }
  function centerOnNode(node) {
    const c = G.canvas, v = G.view; if (!c) return;
    v.tx = c.clientWidth / 2 - node.x * v.scale;
    v.ty = c.clientHeight / 2 - node.y * v.scale;
  }
  function focusNode(node) {
    G.selected = node.id; G.focusNodeId = node.id;
    centerOnNode(node);
    tg && tg.HapticFeedback && tg.HapticFeedback.selectionChanged();
    // Hand the React card an initial payload; it enriches with tags/snippet itself.
    onFocus({ id: node.id, title: node.title || "untitled", path: node.path || "Inbox", links: neighborCount(node.id) });
  }
  function clearFocus() {
    G.selected = null; G.focusNodeId = null; G.focusReq++;
    onFocus(null);
  }

  // ----- folder filter (shared with the Notes feed) + ego subgraph -----
  function filterSig() {
    const f = getFilter();
    return (f ? [...f].sort().join("|") : "ALL") + "|ego:" + (G.ego == null ? "" : G.ego);
  }
  function applyFilter(data) {
    const f = getFilter();
    if (!f) return data;
    const nodes = (data.nodes || []).filter((n) => f.has(n.path || "(unsorted)"));
    const ids = new Set(nodes.map((n) => n.id));
    const edges = (data.edges || []).filter((e) => ids.has(e.source) && ids.has(e.target));
    return { nodes, edges };
  }
  function currentData() {
    const full = applyFilter(G.data || { nodes: [], edges: [] });
    if (G.ego == null) return full;
    const keep = new Set([G.ego]);
    for (const e of full.edges) {
      if (e.source === G.ego) keep.add(e.target);
      if (e.target === G.ego) keep.add(e.source);
    }
    return {
      nodes: full.nodes.filter((n) => keep.has(n.id)),
      edges: full.edges.filter((e) => keep.has(e.source) && keep.has(e.target)),
    };
  }
  function rebuildSim() {
    G.filterSig = filterSig();
    const data = currentData();
    if (!data.nodes.length) {
      stopLoop(); G.sim = null; G.cards = []; publishCards();
      emptyMessage(getFilter() ? "No notes match the folder filter." : "No connections yet — link notes in the bot.");
      return;
    }
    G.sim = buildSim(data, G.canvas.clientWidth, G.canvas.clientHeight);
    for (let i = 0; i < 80; i++) stepSim(G.sim);   // warm up before first paint
    autoFit();
    startLoop();
  }

  // ----- pointer / wheel input -----
  const pointers = new Map(); let last = null, moved = 0, pinch = 0;
  const onDown = (e) => {
    canvas.setPointerCapture(e.pointerId); pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    last = { x: e.clientX, y: e.clientY }; moved = 0;
    if (pointers.size === 2) { const p = [...pointers.values()]; pinch = Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y); }
  };
  const onMove = (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 2) {
      const p = [...pointers.values()], d = Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y);
      if (pinch > 0) { const rect = canvas.getBoundingClientRect(); zoomAt((p[0].x + p[1].x) / 2 - rect.left, (p[0].y + p[1].y) / 2 - rect.top, d / pinch); }
      pinch = d; moved = 999; return;
    }
    if (last) { const dx = e.clientX - last.x, dy = e.clientY - last.y; moved += Math.abs(dx) + Math.abs(dy); G.view.tx += dx; G.view.ty += dy; last = { x: e.clientX, y: e.clientY }; }
  };
  const onUp = (e) => {
    if (!pointers.has(e.pointerId)) return;
    if (pointers.size === 1 && moved < 6) graphTap(e.clientX, e.clientY);
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = 0;
    last = pointers.size === 1 ? [...pointers.values()][0] : null;
  };
  const onWheel = (e) => { e.preventDefault(); const rect = canvas.getBoundingClientRect(); zoomAt(e.clientX - rect.left, e.clientY - rect.top, e.deltaY < 0 ? 1.1 : 0.9); };
  const onResize = () => { sizeCanvas(); autoFit(); };

  function wireInput() {
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointercancel", onUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("resize", onResize);
  }
  function unwireInput() {
    canvas.removeEventListener("pointerdown", onDown);
    canvas.removeEventListener("pointermove", onMove);
    canvas.removeEventListener("pointerup", onUp);
    canvas.removeEventListener("pointercancel", onUp);
    canvas.removeEventListener("wheel", onWheel);
    window.removeEventListener("resize", onResize);
  }

  // ----- public API -----
  return {
    async start() {
      sizeCanvas();
      if (!G._wired) { wireInput(); G._wired = true; }
      if (!G.loaded) { G.loaded = true; G.data = await fetchGraph().catch(() => ({ nodes: [], edges: [] })); }
      if (!G.sim || G.filterSig !== filterSig()) rebuildSim();
      else startLoop();
    },
    stop() { stopLoop(); },
    // Rebuild if the folder filter changed since the last build (called on filter edits).
    syncFilter() { if (G.loaded && G.filterSig !== filterSig()) rebuildSim(); },
    enterEgo() { if (G.focusNodeId == null) return false; G.ego = G.focusNodeId; rebuildSim(); return true; },
    exitEgo() { if (G.ego == null) return false; G.ego = null; rebuildSim(); return true; },
    isEgo() { return G.ego != null; },
    // Lazily enrich the focus card with tags + a snippet from the note detail.
    async loadDetail(id) {
      const req = ++G.focusReq;
      const d = await fetchNote(id).catch(() => null);
      if (req !== G.focusReq || !d) return null;
      return d;
    },
    focusReqId() { return G.focusReq; },
    destroy() { stopLoop(); unwireInput(); },
  };
}
