// Canvas force-directed graph engine (ported from the vanilla map.js).
// Framework-agnostic: the engine owns the canvas, the physics sim, pan/zoom
// input and the focus transition; MapView only renders the card list and passes
// the note-open handler in. Tap focuses a note, hold opens it.
//
// Nodes are drawn as a faint folder-coloured dot plus a note card. The cards are
// real DOM (the shared NoteMiniCard, so the map and the chat tab show the same
// card); this engine only decides which nodes get one and where it sits, and
// reports that through `onCards` (set changed) and `onLayout` (per-frame
// positions). Cards are fixed screen size, so zooming in spreads nodes apart and
// reveals more of them — the semantic zoom falls out of the overlap culling.
import { fetchGraph } from "../lib/api.js";
import { pathColor } from "../lib/format.js";
import { tg } from "../lib/telegram.js";

// Cards are fixed screen-size (they do not scale with zoom); the layout below
// places them in screen space and culls overlaps, so zooming changes density
// rather than card size.
const CARD_W = 200, CARD_H = 48, CARD_GAP = 6, MAX_CARDS = 60, EDGE = 40;

// A tap re-centres the map on a note; holding it opens the action card.
const LONG_PRESS_MS = 450, TAP_SLOP = 6;

// Focusing is a transition, not a switch. `mix` runs on a clock, not a decaying
// lerp — an exponential ease is fastest at its first frame, which is exactly the
// jolt we do not want — and it is shaped by smoothstep, so the motion starts and
// ends at zero velocity. Every depth cue (position, foreshortening, scale, fade,
// blur) and the recentring pan are driven by that one value, so the whole map
// moves as a single body.
const FOCUS_MS = 950;

// Below this the free layout is considered settled and stops moving entirely.
const ALPHA_REST = 0.004;

function lerp(from, to, mix) { return from + (to - from) * mix; }

function smoothstep(t) { return t * t * (3 - 2 * t); }

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

function depthAlpha(d) { return d === 0 ? 1 : Math.max(0.3, 1 - d * 0.25); }

function depthBlur(d) { return d > 1 ? (d - 1) * 0.9 : 0; }

// Where each node sits once the map is fully focused: the tapped note at the hub,
// each depth on its own ring. Ring members keep their current angular order and
// are spread evenly around it at the offset that rotates them least, so the
// layout re-forms by the shortest path instead of scrambling. The outermost ring
// is only pushed outward — its nodes keep their arrangement, since a perfect
// circle of everything-else reads as noise.
function ringLayout(nodes, depth, hub) {
  const rings = new Map();

  for (const n of nodes) {
    const d = Math.min(depth.get(n.id) ?? MAX_DEPTH, MAX_DEPTH);

    if (!rings.has(d)) rings.set(d, []);

    rings.get(d).push(n);
  }

  const target = new Map();

  for (const [d, members] of rings) {
    if (d === 0) {
      for (const n of members) target.set(n.id, { x: hub.x, y: hub.y });
      continue;
    }

    const placed = members
      .map((n) => ({ n, a: Math.atan2(n.y - hub.y, n.x - hub.x), r: Math.hypot(n.x - hub.x, n.y - hub.y) }))
      .sort((p, q) => p.a - q.a);

    if (d === MAX_DEPTH) {
      for (const item of placed) {
        const r = Math.max(item.r, DEPTH_RING[d]);
        target.set(item.n.id, { x: hub.x + Math.cos(item.a) * r, y: hub.y + Math.sin(item.a) * r });
      }
      continue;
    }

    const step = (Math.PI * 2) / placed.length;
    let offset = 0;

    placed.forEach((item, i) => { offset += item.a - i * step; });
    offset /= placed.length;

    placed.forEach((item, i) => {
      const a = offset + i * step;
      target.set(item.n.id, {
        x: hub.x + Math.cos(a) * DEPTH_RING[d],
        y: hub.y + Math.sin(a) * DEPTH_RING[d],
      });
    });
  }

  return target;
}

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
  // Decay all the way to rest. The old 0.03 floor kept every node drifting
  // forever, which read as constant low-level jitter under everything else.
  sim.alpha = a < ALPHA_REST ? 0 : a * 0.978;
}

// One engine instance per mounted canvas. All former GRAPH globals live on G.
export function createGraphEngine(canvas, opts) {
  const G = {
    canvas, ctx: canvas.getContext("2d"), dpr: 1, sim: null, raf: null,
    running: false, loaded: false, selected: null,
    cards: [], cardSig: null, pos: new Map(), vanish: null, lastTs: 0,
    depth: null, depthRoot: null, target: null, marked: null,
    mix: 0, mixT: 0, mixTarget: 0, viewFrom: null, viewTo: null,
    data: null, filterSig: null,
    view: { scale: 1, tx: 0, ty: 0 },
  };
  const getFilter = opts.getFilter || (() => null);   // returns a Set of folder keys, or null = all
  // A tap needs no callback: it rebuilds the map, which is its own feedback.
  const onOpenNote = opts.onOpenNote || (() => {});    // (noteId) → long press opens the note
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
    const v = G.view, mix = G.mix;

    if (!G.depth || mix <= 0) {
      return {
        x: n.x * v.scale + v.tx, y: n.y * v.scale + v.ty,
        k: 1, cardK: 1, d: 0, alpha: 1, blur: 0,
      };
    }

    // Glide from wherever the free layout left this node to its ring slot. This
    // is plain interpolation between two layouts — no forces, so nothing can
    // overshoot, oscillate or lurch.
    const to = G.target && G.target.get(n.id);
    const gx = to ? lerp(n.x, to.x, mix) : n.x;
    const gy = to ? lerp(n.y, to.y, mix) : n.y;
    const sx = gx * v.scale + v.tx, sy = gy * v.scale + v.ty;

    const d = Math.min(G.depth.get(n.id) ?? MAX_DEPTH, MAX_DEPTH);
    const k = 1 / (1 + d * FORESHORTEN * mix);
    const vp = G.vanish || { x: sx, y: sy };

    return {
      x: vp.x + (sx - vp.x) * k,
      y: vp.y + (sy - vp.y) * k,
      k,
      d,
      cardK: lerp(1, cardScale(d), mix),
      alpha: lerp(1, depthAlpha(d), mix),
      blur: depthBlur(d) * mix,
    };
  }

  function drawGraph() {
    const { ctx, canvas, sim, view, dpr } = G; if (!ctx || !sim) return;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const focused = G.depth ? sim.nodes.find((n) => n.id === G.depthRoot) : null;
    const hub = focused && G.target && G.target.get(focused.id);
    G.vanish = focused
      ? {
          x: lerp(focused.x, hub ? hub.x : focused.x, G.mix) * view.scale + view.tx,
          y: lerp(focused.y, hub ? hub.y : focused.y, G.mix) * view.scale + view.ty,
        }
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

      // Only the long-pressed note is marked; a tap says which note the map is
      // built around by putting it front and centre, which needs no chrome.
      if (G.marked === n.id) { ctx.lineWidth = 2; ctx.strokeStyle = "#fff"; ctx.stroke(); }
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
      const k = p.cardK, cw = CARD_W * k, ch = CARD_H * k;
      const x = clamp(p.x - cw / 2, 2, w - cw - 2);
      const y = clamp(p.y + nodeRadius(n) * view.scale * p.k + CARD_GAP, 2, h - ch - 2);
      cards.push({
        id: n.id, x, y, w: cw, h: ch, k,
        depth: p.d, alpha: p.alpha, blur: p.blur, node: n,
        selected: selected === n.id, marked: G.marked === n.id,
      });
    }
    G.cards = cards;
    publishCards();
  }

  // Content changes are rare (a new visible set); positions change every frame.
  // Splitting them keeps React re-renders off the animation path.
  function publishCards() {
    const sig = G.cards.map((c) => c.id + ":" + c.depth).join(",");

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

  // Ease the focus strength and the recentring pan one step. Both are pure
  // animation, so they run per frame rather than being set on the gesture.
  function stepTransition(dt) {
    if (G.mixT !== G.mixTarget) {
      const step = dt / FOCUS_MS;
      G.mixT = G.mixTarget > G.mixT
        ? Math.min(G.mixTarget, G.mixT + step)
        : Math.max(G.mixTarget, G.mixT - step);
      G.mix = smoothstep(G.mixT);

      // Fully unfocused: only now is the ring layout safe to drop, so the unwind
      // has something to unwind from.
      if (G.mixT === 0) { G.depth = null; G.depthRoot = null; G.target = null; G.vanish = null; }
    }

    // The recentring pan rides the same curve, so it cannot drift out of step
    // with the layout. A drag clears it and hands control back.
    if (G.viewFrom && G.viewTo) {
      G.view.tx = lerp(G.viewFrom.tx, G.viewTo.tx, G.mix);
      G.view.ty = lerp(G.viewFrom.ty, G.viewTo.ty, G.mix);

      if (G.mixT === 1 || G.mixT === 0) { G.viewFrom = null; G.viewTo = null; }
    }
  }

  function loop(ts) {
    if (!G.running) return;
    const dt = G.lastTs ? Math.min(64, ts - G.lastTs) : 16;
    G.lastTs = ts;
    stepTransition(dt);

    // While the focus layout owns the positions the free sim has nothing to say,
    // so let it rest rather than drift underneath.
    if (G.mixT < 1) stepSim(G.sim);

    drawGraph();
    G.raf = requestAnimationFrame(loop);
  }
  function startLoop() { if (G.running || !G.sim) return; G.running = true; G.lastTs = 0; G.raf = requestAnimationFrame(loop); }
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

  // Holding a note opens it. Holding empty space does nothing —
  // clearing is the tap's job, and a hold there is usually an aborted pan.
  function graphLongPress(clientX, clientY) {
    const node = nodeAt(clientX, clientY);

    if (node) openNote(node);
  }

  // The hub stays exactly where the tapped note already is, so the note itself
  // never moves in the graph — the rings form around it and the view glides to
  // bring it to the centre, both on the transition's own curve.
  function centerOnHub(hub) {
    const c = G.canvas, v = G.view; if (!c) return;
    G.viewFrom = { tx: v.tx, ty: v.ty };
    G.viewTo = {
      tx: c.clientWidth / 2 - hub.x * v.scale,
      ty: c.clientHeight / 2 - hub.y * v.scale,
    };
  }
  // A tap: re-layout around the note. Depth drives both the ring position and the
  // perspective, so the graph reforms instead of just highlighting. It also drops
  // the held-note marker, which belongs to the long press.
  function selectNode(node, keepMark) {
    G.selected = node.id;
    G.depth = depthsFrom(currentData(), node.id);
    G.depthRoot = node.id;
    // Re-aim from wherever the map is right now, so re-tapping mid-transition
    // continues smoothly instead of restarting.
    freezeCurrentLayout();
    const hub = { x: node.x, y: node.y };
    G.target = ringLayout(G.sim.nodes, G.depth, hub);
    G.mixT = 0; G.mixTarget = 1;
    G.mix = 0;
    centerOnHub(hub);
    startLoop();
    tg && tg.HapticFeedback && tg.HapticFeedback.selectionChanged();

    if (!keepMark) G.marked = null;
  }
  // A long press: focus the note as a tap would, mark it, and open it.
  function openNote(node) {
    selectNode(node, true);
    tg && tg.HapticFeedback && tg.HapticFeedback.impactOccurred
      && tg.HapticFeedback.impactOccurred("medium");
    G.marked = node.id;
    onOpenNote(node.id);
  }
  function clearFocus() {
    G.selected = null; G.marked = null;
    // Leave the ring layout in place; `stepTransition` drops it once the mix
    // reaches 0, so the rings unwind instead of vanishing.
    G.mixTarget = 0;
    G.viewFrom = null; G.viewTo = null;
    startLoop();
  }
  // Bake the currently rendered (part-way) positions back into the sim, so a new
  // focus interpolates from what is on screen rather than from the free layout
  // the viewer can no longer see.
  function freezeCurrentLayout() {
    if (!G.sim || !G.target || G.mix <= 0) return;

    for (const n of G.sim.nodes) {
      const to = G.target.get(n.id);

      if (!to) continue;

      n.x = lerp(n.x, to.x, G.mix); n.y = lerp(n.y, to.y, G.mix);
      n.vx = 0; n.vy = 0;
    }
  }
  // ----- folder filter (shared with the Notes feed) -----
  function filterSig() {
    const f = getFilter();

    return f ? [...f].sort().join("|") : "ALL";
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
    return applyFilter(G.data || { nodes: [], edges: [] });
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
    if (last) { const dx = e.clientX - last.x, dy = e.clientY - last.y; moved += Math.abs(dx) + Math.abs(dy); G.view.tx += dx; G.view.ty += dy; last = { x: e.clientX, y: e.clientY }; G.viewFrom = null; G.viewTo = null; }

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
    destroy() { stopLoop(); cancelPress(); unwireInput(); },
  };
}
