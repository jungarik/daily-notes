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

// A tap re-centres the map on a note; holding it opens the action card.
const LONG_PRESS_MS = 450, TAP_SLOP = 6;

// Focus depth: 0 is the tapped note, 1 its direct neighbours, 2+ the rest of the
// vault falling away behind them. DEPTH_RING is the sim-space radius each ring
// settles at; FORESHORTEN then projects those rings toward the tapped note so
// the far ones compress together the way distance does in perspective.
const MAX_DEPTH = 3;
const DEPTH_RING = [0, 118, 215, 300];
const FORESHORTEN = 0.26;

function clamp(v, lo, hi) { return hi < lo ? lo : Math.max(lo, Math.min(hi, v)); }

// How much a card shrinks with depth — gentler than the positional
// foreshortening, so a neighbour stays readable instead of vanishing.
function cardScale(d) { return Math.max(0.6, 1 - d * 0.17); }

// Breadth-first distance from the tapped note; anything unreachable sits on the
// furthest ring.
function depthsFrom(data, rootId) {
  const adj = new Map();
  const add = (a, b) => {
    if (!adj.has(a)) adj.set(a, []);
    adj.get(a).push(b);
  };

  for (const e of data.edges || []) { add(e.source, e.target); add(e.target, e.source); }

  const depth = new Map([[rootId, 0]]);
  let frontier = [rootId];

  for (let d = 1; d <= MAX_DEPTH && frontier.length; d++) {
    const next = [];
    for (const id of frontier) {
      for (const nb of adj.get(id) || []) {
        if (depth.has(nb)) continue;
        depth.set(nb, d);
        next.push(nb);
      }
    }
    frontier = next;
  }

  return depth;
}

// A faint folder-coloured dot anchors every node; the card carries the detail.
function nodeRadius(n) { return 3 + Math.min(6, (n.degree || 0) * 0.8); }

function buildSim(data, W, H) {
  const spread = Math.min(W, H) * 0.5 || 200;
  const nodes = data.nodes.map((n) => ({ ...n, x: (Math.random() - .5) * spread, y: (Math.random() - .5) * spread, vx: 0, vy: 0 }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges = (data.edges || []).map((e) => ({ a: byId.get(e.source), b: byId.get(e.target) })).filter((e) => e.a && e.b);
  return { nodes, edges, alpha: 1 };
}

function stepSim(sim, depth) {
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
    if (depth) {
      // With a note focused the layout re-forms as concentric rings around it:
      // the note itself is pinned to the origin, everything else is sprung
      // toward the radius of its depth.
      const d = Math.min(depth.get(n.id) ?? MAX_DEPTH, MAX_DEPTH);

      if (d === 0) { n.vx += -n.x * 0.30; n.vy += -n.y * 0.30; }
      else {
        const r = Math.hypot(n.x, n.y) || 0.01, f = (r - DEPTH_RING[d]) * 0.05;
        n.vx += -n.x / r * f; n.vy += -n.y / r * f;
      }
    } else {
      n.vx += -n.x * CENTER; n.vy += -n.y * CENTER;
    }
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
    cards: [], cardSig: null, depth: null, pos: new Map(), vanish: null,
    ego: null, focusReq: 0, data: null, filterSig: null,
    view: { scale: 1, tx: 0, ty: 0 },
  };
  const getFilter = opts.getFilter || (() => null);   // returns a Set of folder keys, or null = all
  const onSelect = opts.onSelect || (() => {});         // (node|null) → tap: which note the map is built around
  const onFocus = opts.onFocus || (() => {});          // (node|null) → long press: the action card
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

  // Screen position for one node, foreshortened by its depth. With nothing
  // focused this is the plain pan/zoom transform; with a focus, everything
  // recedes toward the tapped note, which is the vanishing point.
  function project(n) {
    const v = G.view;
    const sx = n.x * v.scale + v.tx, sy = n.y * v.scale + v.ty;

    if (!G.depth) return { x: sx, y: sy, k: 1, d: 0, alpha: 1 };

    const d = Math.min(G.depth.get(n.id) ?? MAX_DEPTH, MAX_DEPTH);
    const k = 1 / (1 + d * FORESHORTEN);
    const vp = G.vanish || { x: sx, y: sy };

    return {
      x: vp.x + (sx - vp.x) * k,
      y: vp.y + (sy - vp.y) * k,
      k,
      d,
      alpha: d === 0 ? 1 : Math.max(0.3, 1 - d * 0.25),
    };
  }

  function drawGraph() {
    const { ctx, canvas, sim, view, dpr, selected } = G; if (!ctx || !sim) return;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const focused = G.depth ? sim.nodes.find((n) => n.id === G.focusNodeId) : null;
    G.vanish = focused
      ? { x: focused.x * view.scale + view.tx, y: focused.y * view.scale + view.ty }
      : null;

    const pos = new Map();
    for (const n of sim.nodes) pos.set(n.id, project(n));
    G.pos = pos;

    // Edges fade with the shallower of their two endpoints, so a link into the
    // background dims with it.
    for (const e of sim.edges) {
      const a = pos.get(e.a.id), b = pos.get(e.b.id);
      ctx.globalAlpha = Math.min(a.alpha, b.alpha) * 0.55;
      ctx.strokeStyle = "rgba(255,255,255,.22)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }

    for (const n of sim.nodes) {
      const p = pos.get(n.id);
      ctx.globalAlpha = p.alpha;
      ctx.beginPath();
      ctx.arc(p.x, p.y, Math.max(1.2, nodeRadius(n) * view.scale * p.k), 0, Math.PI * 2);
      ctx.fillStyle = pathColor(n.path); ctx.fill();

      if (selected === n.id) { ctx.lineWidth = 2; ctx.strokeStyle = "#fff"; ctx.stroke(); }
    }

    ctx.globalAlpha = 1;
    layoutCards();
  }

  // Every node in view gets a card, and they are allowed to overlap: the result
  // is a heap. Nearest depth wins the top of the pile, and within a depth the
  // most-linked note does — so the tapped note sits in front, its neighbours
  // just behind it, and the rest of the vault stacks up in the background.
  // `cards` is ordered front-to-back, which is both the stacking order (React
  // maps it to a descending z-index) and the hit-test order.
  function layoutCards() {
    const { sim, view, selected, canvas, pos } = G;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    const ordered = [...sim.nodes].sort((x, y) => {
      const dx = pos.get(x.id).d, dy = pos.get(y.id).d;

      return dx !== dy ? dx - dy : (y.degree || 0) - (x.degree || 0);
    });
    const cards = [];
    for (const n of ordered) {
      if (cards.length >= MAX_CARDS) break;
      const p = pos.get(n.id);

      if (p.x < -EDGE || p.x > w + EDGE || p.y < -EDGE || p.y > h + EDGE) continue;

      // Cards keep their full width — an edge card is nudged back inside rather
      // than sliced off, since in a heap it is already offset from its dot.
      const k = cardScale(p.d), cw = CARD_W * k, ch = CARD_H * k;
      const x = clamp(p.x - cw / 2, 2, w - cw - 2);
      const y = clamp(p.y + nodeRadius(n) * view.scale * p.k + CARD_GAP, 2, h - ch - 2);
      cards.push({
        id: n.id, x, y, w: cw, h: ch, k,
        depth: p.d, alpha: p.alpha, node: n, selected: selected === n.id,
      });
    }
    G.cards = cards;
    publishCards();
  }

  // Content changes are rare (a new visible set); positions change every frame.
  // Splitting them keeps React re-renders off the animation path.
  function publishCards() {
    const sig = G.cards.map((c) => c.id + ":" + c.depth + (c.selected ? "*" : "")).join(",");

    if (sig !== G.cardSig) {
      G.cardSig = sig;
      onCards(G.cards.map((c) => ({
        id: c.node.id,
        title: c.node.title,
        path: c.node.path,
        degree: c.node.degree,
        created_at: c.node.created_at,
        attachments: c.node.attachments,
        depth: c.depth,
      })));
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
    stepSim(G.sim, G.depth); drawGraph();
    G.raf = requestAnimationFrame(loop);
  }
  function startLoop() { if (G.running || !G.sim) return; G.running = true; G.raf = requestAnimationFrame(loop); }
  function stopLoop() { G.running = false; if (G.raf) cancelAnimationFrame(G.raf); G.raf = null; }

  function zoomAt(cx, cy, factor) {
    const v = G.view, gx = (cx - v.tx) / v.scale, gy = (cy - v.ty) / v.scale;
    v.scale = Math.max(0.2, Math.min(4, v.scale * factor));
    v.tx = cx - gx * v.scale; v.ty = cy - gy * v.scale;
  }

  // Which note is under a screen point: the topmost card covering it, else the
  // nearest dot. Shared by the tap and the long press.
  function nodeAt(clientX, clientY) {
    const c = G.canvas, rect = c.getBoundingClientRect(), v = G.view;
    const px = clientX - rect.left, py = clientY - rect.top;

    const hit = (card) => px >= card.x && px <= card.x + card.w
                       && py >= card.y && py <= card.y + card.h;
    const top = G.cards.find((card) => card.selected && hit(card)) || G.cards.find(hit);

    if (top) return top.node;

    // Dots are matched against their *projected* positions — under perspective a
    // node is not where the plain pan/zoom transform would put it.
    let best = null, bestd = 1e9;
    for (const n of (G.sim ? G.sim.nodes : [])) {
      const p = G.pos.get(n.id);

      if (!p) continue;

      const r = nodeRadius(n) * v.scale * p.k + 10;
      const dx = p.x - px, dy = p.y - py, d = dx * dx + dy * dy;

      if (d < r * r && d < bestd) { best = n; bestd = d; }
    }

    return best;
  }

  function graphTap(clientX, clientY) {
    const node = nodeAt(clientX, clientY);

    if (node) selectNode(node); else clearFocus();
  }

  // Holding a note opens its action card. Holding empty space does nothing —
  // clearing is the tap's job, and a hold there is usually an aborted pan.
  function graphLongPress(clientX, clientY) {
    const node = nodeAt(clientX, clientY);

    if (node) openActionCard(node);
  }

  function neighborCount(id) {
    const edges = (G.data && G.data.edges) || [];
    let n = 0;
    for (const e of edges) if (e.source === id || e.target === id) n++;
    return n;
  }
  // The focused note is pinned to the sim origin, so the view centres there and
  // the note travels to the middle as the rings form around it.
  function centerOnOrigin() {
    const c = G.canvas, v = G.view; if (!c) return;
    v.tx = c.clientWidth / 2;
    v.ty = c.clientHeight / 2;
  }
  // The payload React needs for either the highlight or the action card; the
  // card enriches it with tags/snippet itself.
  function nodeSummary(node) {
    return {
      id: node.id,
      title: node.title || "untitled",
      path: node.path || "Inbox",
      links: neighborCount(node.id),
    };
  }
  // A tap: re-layout around the note. Depth drives both the ring physics and the
  // perspective, so the graph reforms instead of just highlighting — and any open
  // action card is dismissed, since that belongs to a long press.
  function selectNode(node, keepCard) {
    G.selected = node.id; G.focusNodeId = node.id;
    G.depth = depthsFrom(currentData(), node.id);
    reheat();
    centerOnOrigin();
    tg && tg.HapticFeedback && tg.HapticFeedback.selectionChanged();
    onSelect(nodeSummary(node));

    if (!keepCard) onFocus(null);
  }
  // A long press: same note, plus the Neighbors / Open note / Outline card.
  function openActionCard(node) {
    selectNode(node, true);
    tg && tg.HapticFeedback && tg.HapticFeedback.impactOccurred
      && tg.HapticFeedback.impactOccurred("medium");
    onFocus(nodeSummary(node));
  }
  function clearFocus() {
    G.selected = null; G.focusNodeId = null; G.focusReq++;
    G.depth = null; G.vanish = null;
    reheat();
    onSelect(null);
    onFocus(null);
  }
  // Wake the sim so it can settle into (or out of) the focused ring layout.
  function reheat() {
    if (!G.sim) return;
    G.sim.alpha = Math.max(G.sim.alpha, 0.55);
    startLoop();
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
    for (let i = 0; i < 80; i++) stepSim(G.sim, G.depth);   // warm up before first paint
    autoFit();
    startLoop();
  }

  // ----- pointer / wheel input -----
  const pointers = new Map(); let last = null, moved = 0, pinch = 0;
  // The long-press timer fires while the finger is still down, so the action card
  // appears on the hold itself. Any drag, pinch or early release cancels it.
  let pressTimer = null, pressFired = false;
  const cancelPress = () => {
    if (pressTimer) clearTimeout(pressTimer);
    pressTimer = null;
  };
  const onDown = (e) => {
    canvas.setPointerCapture(e.pointerId); pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    last = { x: e.clientX, y: e.clientY }; moved = 0;
    cancelPress();

    if (pointers.size === 1) {
      pressFired = false;
      const at = { x: e.clientX, y: e.clientY };
      pressTimer = setTimeout(() => {
        pressTimer = null; pressFired = true;
        graphLongPress(at.x, at.y);
      }, LONG_PRESS_MS);
    } else {
      const p = [...pointers.values()]; pinch = Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y);
    }
  };
  const onMove = (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 2) {
      const p = [...pointers.values()], d = Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y);
      if (pinch > 0) { const rect = canvas.getBoundingClientRect(); zoomAt((p[0].x + p[1].x) / 2 - rect.left, (p[0].y + p[1].y) / 2 - rect.top, d / pinch); }
      pinch = d; moved = 999; cancelPress(); return;
    }
    if (last) { const dx = e.clientX - last.x, dy = e.clientY - last.y; moved += Math.abs(dx) + Math.abs(dy); G.view.tx += dx; G.view.ty += dy; last = { x: e.clientX, y: e.clientY }; }

    if (moved > TAP_SLOP) cancelPress();
  };
  const onUp = (e) => {
    if (!pointers.has(e.pointerId)) return;
    cancelPress();

    if (pointers.size === 1 && moved < TAP_SLOP && !pressFired) graphTap(e.clientX, e.clientY);

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
    destroy() { stopLoop(); cancelPress(); unwireInput(); },
  };
}
