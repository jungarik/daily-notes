// Canvas graph engine: the vault as a globe.
//
// Notes are laid out *on* a sphere — a force-directed simulation whose nodes are
// unit vectors, so repulsion spreads them over the whole surface while links pull
// connected notes together. Dragging rolls the globe under the finger (a rotation
// about the axis perpendicular to the drag, by arc length / radius), two fingers
// scale it, and the folder filter decides which notes are on it at all.
//
// Framework-agnostic: the engine owns the canvas, the simulation, the rotation
// and the pulses; MapView only renders the card list and passes the note-open
// handler in. Tapping a note sends a pulse of light down each of its wires to the
// notes it links to; holding one opens it.
//
// Nodes draw as a faint folder-coloured dot plus a note card. The cards are real
// DOM (the shared NoteMiniCard, so the map and the chat tab show the same card);
// this engine only decides which nodes get one and where it sits, and reports
// that through `onCards` (set changed) and `onLayout` (per-frame positions).
import { fetchGraph } from "../lib/api.js";
import { pathColor } from "../lib/format.js";
import { tg } from "../lib/telegram.js";

// Cards are fixed screen-size, so scaling the globe changes how many fit rather
// than how big they are.
const CARD_W = 200, CARD_H = 48, CARD_GAP = 6, MAX_CARDS = 60;

// A tap pulses a note's links; holding it opens the note.
const LONG_PRESS_MS = 450, TAP_SLOP = 6;

// A tap fires a photon down every wire leaving the note, carrying the note's
// folder colour, and the arrival flashes the far dot — so a tap answers "what
// does this connect to?" without disturbing the layout.
const PHOTON_MS = 620, PHOTON_TAIL = 0.14, FLASH_MS = 520;

// Below this the layout is settled and stops moving entirely.
const ALPHA_REST = 0.004;

// How much of the viewport the globe fills at scale 1, and how far either side of
// the horizon a node fades over so nothing pops in or out.
const GLOBE_FILL = 0.42, LIMB_FADE = 0.28;

// Notes round the back are never hidden — the globe is see-through, so the whole
// vault stays countable at a glance. Past the horizon a note shrinks to
// GHOST_SCALE and fades to GHOST_ALPHA instead, and the near face draws over it.
const GHOST_SCALE = 0.55, GHOST_ALPHA = 0.14;

function lerp(from, to, mix) { return from + (to - from) * mix; }

function smoothstep(t) { return t * t * (3 - 2 * t); }

function clamp(v, lo, hi) { return hi < lo ? lo : Math.max(lo, Math.min(hi, v)); }

// Sharpness is a matter of where a note is on screen, not how far it is from the
// tapped one: a focus square sits at the centre of the view and anything inside
// it is sharp, so rolling a note towards the middle brings it into focus. Outside
// the square, blur ramps up with how far past the border the note has fallen.
// The card is what you read and follow, so it stays put — centred on the note's
// place on the globe — and the *dot* moves out of its way instead: below the card
// in the top half of the view, above it in the bottom half. Dots therefore gather
// towards the midline, and since edges terminate at dots, the connection lines
// run through the middle band rather than under the cards. A small circle sliding
// is also far easier to ignore than a card jumping.
// Switching the instant a note crosses the midline would still snap the dot, so
// each carries an eased 0..1 side and slides across over SIDE_MS.
const SIDE_MS = 260;

const FOCUS_BOX = 0.6;      // square side, as a fraction of the shorter viewport edge
const BLUR_MAX = 2.4;       // px of blur at full defocus
const BLUR_FALLOFF = 150;   // px outside the border over which blur reaches BLUR_MAX

function focusBlur(x, y, w, h) {
  const half = Math.min(w, h) * FOCUS_BOX / 2;
  const dx = Math.max(0, Math.abs(x - w / 2) - half);
  const dy = Math.max(0, Math.abs(y - h / 2) - half);

  if (!dx && !dy) return 0;

  return Math.min(BLUR_MAX, (Math.hypot(dx, dy) / BLUR_FALLOFF) * BLUR_MAX);
}

// ----- rotation (3x3, row-major) -------------------------------------------
// The view is a rotation, not a pan. Incremental drag rotations are applied on
// the *left*, i.e. in camera space, which is what makes the surface follow the
// finger instead of spinning about fixed world axes.

function identity() { return [1, 0, 0, 0, 1, 0, 0, 0, 1]; }

function multiply(a, b) {
  const out = new Array(9);

  for (let r = 0; r < 3; r++) {
    for (let c = 0; c < 3; c++) {
      out[r * 3 + c] = a[r * 3] * b[c] + a[r * 3 + 1] * b[3 + c] + a[r * 3 + 2] * b[6 + c];
    }
  }

  return out;
}

function applyRotation(m, v) {
  return {
    x: m[0] * v.x + m[1] * v.y + m[2] * v.z,
    y: m[3] * v.x + m[4] * v.y + m[5] * v.z,
    z: m[6] * v.x + m[7] * v.y + m[8] * v.z,
  };
}

// Rodrigues' rotation about an arbitrary axis.
function rotationAbout(ax, ay, az, angle) {
  const len = Math.hypot(ax, ay, az);

  if (!len || !angle) return identity();

  const x = ax / len, y = ay / len, z = az / len;
  const c = Math.cos(angle), s = Math.sin(angle), t = 1 - c;

  return [
    t * x * x + c, t * x * y - s * z, t * x * z + s * y,
    t * x * y + s * z, t * y * y + c, t * y * z - s * x,
    t * x * z - s * y, t * y * z + s * x, t * z * z + c,
  ];
}

// Float error accumulates over thousands of drag rotations and would slowly
// shear the globe; Gram-Schmidt puts the matrix back on the rails.
function orthonormalise(m) {
  const r0 = [m[0], m[1], m[2]];
  let len = Math.hypot(...r0) || 1;
  r0[0] /= len; r0[1] /= len; r0[2] /= len;

  const dot = m[3] * r0[0] + m[4] * r0[1] + m[5] * r0[2];
  const r1 = [m[3] - dot * r0[0], m[4] - dot * r0[1], m[5] - dot * r0[2]];
  len = Math.hypot(...r1) || 1;
  r1[0] /= len; r1[1] /= len; r1[2] /= len;

  const r2 = [
    r0[1] * r1[2] - r0[2] * r1[1],
    r0[2] * r1[0] - r0[0] * r1[2],
    r0[0] * r1[1] - r0[1] * r1[0],
  ];

  return [...r0, ...r1, ...r2];
}

// ----- the layout, on the sphere --------------------------------------------

// A faint folder-coloured dot anchors every node; the card carries the detail.
function nodeRadius(n) { return 3 + Math.min(6, (n.degree || 0) * 0.8); }

// Seed on a Fibonacci spiral: the cheapest way to cover a sphere evenly, so the
// simulation starts from full coverage and only has to pull linked notes
// together rather than discover the spread itself.
function seedSphere(count, index) {
  const y = count === 1 ? 0 : 1 - (index / (count - 1)) * 2;
  const r = Math.sqrt(Math.max(0, 1 - y * y));
  const theta = Math.PI * (3 - Math.sqrt(5)) * index;

  return { x: Math.cos(theta) * r, y, z: Math.sin(theta) * r };
}

function buildSim(data) {
  const count = data.nodes.length;
  const nodes = data.nodes.map((n, i) => ({ ...n, ...seedSphere(count, i), vx: 0, vy: 0, vz: 0 }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges = (data.edges || [])
    .map((e) => ({ a: byId.get(e.source), b: byId.get(e.target) }))
    .filter((e) => e.a && e.b);

  return { nodes, edges, alpha: 1 };
}

// Forces act on the chord between two nodes; after integrating, every node is
// pushed back onto the unit sphere and its velocity flattened into the tangent
// plane, so everything slides along the surface instead of leaving it.
function stepSim(sim) {
  const nodes = sim.nodes, a = sim.alpha;
  const REPEL = 0.22, SPRING = 0.055, LINK_CHORD = 0.6, DAMP = 0.82;

  for (let i = 0; i < nodes.length; i++) {
    const ni = nodes[i];
    for (let j = i + 1; j < nodes.length; j++) {
      const nj = nodes[j];
      let dx = ni.x - nj.x, dy = ni.y - nj.y, dz = ni.z - nj.z;
      let d2 = dx * dx + dy * dy + dz * dz;

      if (d2 < 1e-6) {
        dx = Math.random() - .5; dy = Math.random() - .5; dz = Math.random() - .5;
        d2 = dx * dx + dy * dy + dz * dz + 1e-6;
      }

      const inv = 1 / Math.sqrt(d2), f = REPEL / Math.max(d2, 0.02);
      const fx = dx * inv * f, fy = dy * inv * f, fz = dz * inv * f;
      ni.vx += fx; ni.vy += fy; ni.vz += fz;
      nj.vx -= fx; nj.vy -= fy; nj.vz -= fz;
    }
  }

  for (const e of sim.edges) {
    const dx = e.b.x - e.a.x, dy = e.b.y - e.a.y, dz = e.b.z - e.a.z;
    const d = Math.hypot(dx, dy, dz) || 1e-4;
    const f = (d - LINK_CHORD) * SPRING;
    const fx = dx / d * f, fy = dy / d * f, fz = dz / d * f;
    e.a.vx += fx; e.a.vy += fy; e.a.vz += fz;
    e.b.vx -= fx; e.b.vy -= fy; e.b.vz -= fz;
  }

  for (const n of nodes) {
    n.x += n.vx * a; n.y += n.vy * a; n.z += n.vz * a;

    const len = Math.hypot(n.x, n.y, n.z) || 1;
    n.x /= len; n.y /= len; n.z /= len;

    const radial = n.vx * n.x + n.vy * n.y + n.vz * n.z;
    n.vx = (n.vx - radial * n.x) * DAMP;
    n.vy = (n.vy - radial * n.y) * DAMP;
    n.vz = (n.vz - radial * n.z) * DAMP;
  }

  sim.alpha = a < ALPHA_REST ? 0 : a * 0.978;
}

// One engine instance per mounted canvas.
export function createGraphEngine(canvas, opts) {
  const G = {
    canvas, ctx: canvas.getContext("2d"), dpr: 1, sim: null, raf: null,
    running: false, loaded: false, lastTs: 0,
    cards: [], cardSig: null, pos: new Map(), dots: new Map(), sides: new Map(), dt: 16,
    marked: null, photons: [], flashes: new Map(),
    data: null, filterSig: null, spins: 0,
    rot: identity(), scale: 1,
  };
  const getFilter = opts.getFilter || (() => null);   // a Set of folder keys, or null = all
  // A tap needs no callback: the globe turning is its own feedback.
  const onOpenNote = opts.onOpenNote || (() => {});    // (noteId) → long press opens the note
  const onCards = opts.onCards || (() => {});          // (nodes[]) → the visible card set changed
  const onLayout = opts.onLayout || (() => {});        // (cards[]) → per-frame screen positions

  function sizeCanvas() {
    const c = G.canvas; if (!c) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2); G.dpr = dpr;
    c.width = Math.round(c.clientWidth * dpr); c.height = Math.round(c.clientHeight * dpr);
  }

  function globeRadius() {
    const c = G.canvas;

    return Math.min(c.clientWidth, c.clientHeight) * GLOBE_FILL * G.scale;
  }

  function centre() {
    const c = G.canvas;

    return { x: c.clientWidth / 2, y: c.clientHeight / 2 };
  }

  // The globe always fits by construction, so "fit" is just a neutral pose.
  function autoFit() { G.scale = 1; G.rot = identity(); }

  function spinBy(m) { G.rot = multiply(m, G.rot); }

  // A node's place on screen. `tilt` is how square-on it is (1 facing the viewer,
  // 0 at the horizon); `vis` is how far onto the near face it is (1 in front, 0
  // round the back), which decides whether it can be touched. Neither hides it:
  // size and opacity only fall to the ghost floor.
  function project(n) {
    const c = applyRotation(G.rot, n);
    const R = globeRadius(), o = centre();
    const tilt = clamp(c.z, 0, 1);
    const vis = clamp((c.z + LIMB_FADE) / (LIMB_FADE * 2), 0, 1);

    return {
      x: o.x + R * c.x,
      y: o.y + R * c.y,
      z: c.z, tilt, vis,
      // Cards keep most of their size across the face and lose a little towards
      // the horizon; behind it they keep shrinking to the ghost size.
      cardK: c.z >= 0 ? lerp(0.72, 1, c.z) : lerp(0.72, GHOST_SCALE, -c.z),
      dotK: Math.max(GHOST_SCALE, tilt),
      alpha: lerp(GHOST_ALPHA, 1, vis),
    };
  }

  function drawGraph() {
    const { ctx, canvas, sim, dpr } = G; if (!ctx || !sim) return;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const pos = new Map();
    for (const n of sim.nodes) pos.set(n.id, project(n));
    G.pos = pos;
    easeSides(G.dt, h);
    placeDots(h);

    // An edge reaching round the back takes the fainter end's opacity, so links
    // into the far side read as ghosts too rather than vanishing.
    for (const e of sim.edges) {
      const a = pos.get(e.a.id), b = pos.get(e.b.id);
      const da = G.dots.get(e.a.id), db = G.dots.get(e.b.id);
      ctx.globalAlpha = Math.min(a.alpha, b.alpha) * 0.55;
      ctx.strokeStyle = "rgba(255,255,255,.22)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(da.x, da.y); ctx.lineTo(db.x, db.y); ctx.stroke();
    }

    for (const n of sim.nodes) {
      const p = pos.get(n.id);
      const d = G.dots.get(n.id);
      ctx.globalAlpha = p.alpha;
      ctx.beginPath();
      ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
      ctx.fillStyle = pathColor(n.path); ctx.fill();

      if (G.marked === n.id) { ctx.lineWidth = 2; ctx.strokeStyle = "#fff"; ctx.stroke(); }
    }

    drawPulses();
    ctx.globalAlpha = 1;
    layoutCards();
  }

  // Nudge every card towards the side its dot now calls for. A card first seen
  // starts already on its side — only a dot that actually crosses the midline
  // animates.
  function easeSides(dt, h) {
    const mid = h / 2, step = dt / SIDE_MS;

    for (const n of G.sim.nodes) {
      const want = G.pos.get(n.id).y < mid ? 1 : 0;
      const at = G.sides.get(n.id);

      if (at === undefined) { G.sides.set(n.id, want); continue; }

      G.sides.set(n.id, want > at ? Math.min(want, at + step) : Math.max(want, at - step));
    }
  }

  // Photons in flight, then the flash left where one landed. Both are drawn over
  // the dots so an arrival reads as light hitting the note.
  function drawPulses() {
    const { ctx } = G;
    ctx.lineCap = "round";

    for (const ph of G.photons) {
      const from = G.dots.get(ph.from), to = G.dots.get(ph.to);
      const pf = G.pos.get(ph.from), pt = G.pos.get(ph.to);

      if (!from || !to || !pf || !pt) continue;

      const head = clamp(ph.t, 0, 1), tail = Math.max(0, head - PHOTON_TAIL);
      const hx = lerp(from.x, to.x, head), hy = lerp(from.y, to.y, head);
      const tx = lerp(from.x, to.x, tail), ty = lerp(from.y, to.y, tail);
      const trail = ctx.createLinearGradient(tx, ty, hx, hy);
      trail.addColorStop(0, "rgba(255,255,255,0)");
      trail.addColorStop(1, ph.colour);

      ctx.globalAlpha = Math.min(pf.alpha, pt.alpha);
      ctx.strokeStyle = trail; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(tx, ty); ctx.lineTo(hx, hy); ctx.stroke();
      ctx.beginPath(); ctx.arc(hx, hy, 2.6, 0, Math.PI * 2);
      ctx.fillStyle = "#fff"; ctx.fill();
    }

    for (const [id, life] of G.flashes) {
      const dot = G.dots.get(id), p = G.pos.get(id);

      if (!dot || !p) continue;

      ctx.globalAlpha = life * p.alpha;
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(dot.x, dot.y, dot.r + (1 - life) * 11, 0, Math.PI * 2);
      ctx.stroke();
    }

    ctx.lineWidth = 1;
  }

  // Push each dot clear of its card, on the side facing the midline: below the
  // card in the top half of the view, above it in the bottom half. Every dot —
  // and so every edge endpoint — therefore gathers into the band across the
  // middle, which is the one place no card sits. The eased side means a note
  // crossing the line slides its dot across rather than snapping it.
  function placeDots(h) {
    const dots = new Map();

    for (const n of G.sim.nodes) {
      const p = G.pos.get(n.id);
      const r = Math.max(1.2, nodeRadius(n) * G.scale * p.dotK);
      const side = smoothstep(G.sides.get(n.id) ?? (p.y < h / 2 ? 1 : 0));
      const inward = (CARD_H * p.cardK) / 2 + CARD_GAP + r;
      dots.set(n.id, { x: p.x, y: lerp(p.y - inward, p.y + inward, side), r });
    }

    G.dots = dots;
  }

  // Every note gets a card — the ones round the back as ghosts — and they are
  // allowed to overlap: the result is a heap, with the note nearest the viewer on
  // top, so the near face always draws over the far one. `cards` is ordered
  // front-to-back, which is both the stacking order (React maps it to a
  // descending z-index) and the hit-test order.
  function layoutCards() {
    const { sim, canvas, pos } = G;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    // Nearest the viewer sits on top of the heap.
    const ordered = [...sim.nodes].sort((x, y) => pos.get(y.id).z - pos.get(x.id).z);
    const cards = [];

    for (const n of ordered) {
      if (cards.length >= MAX_CARDS) break;

      const p = pos.get(n.id);

      // Cards keep their full width — one near the edge of the viewport is nudged
      // back inside rather than sliced off, since in a heap it is already offset
      // from its dot.
      const k = p.cardK, cw = CARD_W * k, ch = CARD_H * k;
      const x = clamp(p.x - cw / 2, 2, w - cw - 2);
      // The card sits centred on the note's place on the globe and never shifts
      // relative to it, so it is easy to follow while rolling. Its dot is what
      // steps aside.
      const y = clamp(p.y - ch / 2, 2, h - ch - 2);
      cards.push({
        id: n.id, x, y, w: cw, h: ch, k,
        alpha: p.alpha, node: n,
        blur: focusBlur(x + cw / 2, y + ch / 2, w, h),
        marked: G.marked === n.id,
        ghost: p.vis < 0.5,
      });
    }

    G.cards = cards;
    publishCards();
  }

  // Content changes are rare (a new visible set); positions change every frame.
  // Splitting them keeps React re-renders off the animation path.
  function publishCards() {
    const sig = G.cards.map((c) => c.id).join(",");

    if (sig !== G.cardSig) {
      G.cardSig = sig;
      onCards(G.cards.map((c) => ({
        id: c.node.id,
        title: c.node.title,
        path: c.node.path,
        degree: c.node.degree,
        created_at: c.node.created_at,
        attachments: c.node.attachments,
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

  // Advance every photon, hand a flash to whatever it reaches, and let the
  // flashes fade. Nothing here touches the layout — a pulse is pure light.
  function stepPulses(dt) {
    if (G.photons.length) {
      const step = dt / PHOTON_MS;

      for (const ph of G.photons) {
        ph.t += step;

        if (ph.t >= 1) G.flashes.set(ph.to, 1);
      }

      G.photons = G.photons.filter((ph) => ph.t < 1);
    }

    for (const [id, life] of G.flashes) {
      const next = life - dt / FLASH_MS;

      if (next <= 0) G.flashes.delete(id); else G.flashes.set(id, next);
    }
  }

  function loop(ts) {
    if (!G.running) return;
    const dt = G.lastTs ? Math.min(64, ts - G.lastTs) : 16;
    G.lastTs = ts; G.dt = dt;
    stepPulses(dt);

    if (G.sim.alpha > 0) stepSim(G.sim);

    drawGraph();
    G.raf = requestAnimationFrame(loop);
  }
  function startLoop() { if (G.running || !G.sim) return; G.running = true; G.lastTs = 0; G.raf = requestAnimationFrame(loop); }
  function stopLoop() { G.running = false; if (G.raf) cancelAnimationFrame(G.raf); G.raf = null; }

  // Two fingers (or the wheel) scale the globe itself.
  function zoom(factor) { G.scale = clamp(G.scale * factor, 0.55, 4); }

  // Which note is under a screen point: the topmost card covering it, else the
  // nearest dot on the near face. Shared by the tap and the long press.
  function nodeAt(clientX, clientY) {
    const rect = G.canvas.getBoundingClientRect();
    const px = clientX - rect.left, py = clientY - rect.top;

    const hit = (card) => px >= card.x && px <= card.x + card.w
                       && py >= card.y && py <= card.y + card.h;
    const top = G.cards.find((card) => !card.ghost && hit(card));

    if (top) return top.node;

    let best = null, bestd = 1e9;
    for (const n of (G.sim ? G.sim.nodes : [])) {
      const p = G.pos.get(n.id);

      if (!p || p.vis < 0.5) continue;   // round the back: visible, not touchable

      const dot = G.dots.get(n.id) || { x: p.x, y: p.y, r: nodeRadius(n) };
      const r = dot.r + 10;
      const dx = dot.x - px, dy = dot.y - py, d = dx * dx + dy * dy;

      if (d < r * r && d < bestd) { best = n; bestd = d; }
    }

    return best;
  }

  function graphTap(clientX, clientY) {
    const node = nodeAt(clientX, clientY);

    // Tapping the globe itself just drops the held-note marker.
    if (node) pulseFrom(node); else G.marked = null;
  }

  // Holding a note opens it. Holding empty space does nothing — clearing is the
  // tap's job, and a hold there is usually an aborted roll.
  function graphLongPress(clientX, clientY) {
    const node = nodeAt(clientX, clientY);

    if (node) openNote(node);
  }

  // A tap: send a photon down every wire leaving this note. The layout does not
  // move — the light is the whole answer.
  function pulseFrom(node) {
    const colour = pathColor(node.path);

    for (const e of G.sim.edges) {
      const other = e.a.id === node.id ? e.b : (e.b.id === node.id ? e.a : null);

      if (!other) continue;

      G.photons.push({ from: node.id, to: other.id, t: 0, colour });
    }

    G.flashes.set(node.id, 1);
    tg && tg.HapticFeedback && tg.HapticFeedback.selectionChanged();
    startLoop();
  }
  // A long press marks the note and opens it.
  function openNote(node) {
    tg && tg.HapticFeedback && tg.HapticFeedback.impactOccurred
      && tg.HapticFeedback.impactOccurred("medium");
    G.marked = node.id;
    onOpenNote(node.id);
    startLoop();
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
  // Filtering rebuilds the globe: the remaining notes spread out to cover it
  // again rather than leaving holes where the filtered-out ones were.
  function rebuildSim() {
    G.filterSig = filterSig();
    const data = currentData();

    if (!data.nodes.length) {
      stopLoop(); G.sim = null; G.cards = []; G.cardSig = null; publishCards();
      emptyMessage(getFilter() ? "No notes match the folder filter." : "No connections yet — link notes in the bot.");
      return;
    }

    G.sim = buildSim(data);
    G.sides = new Map();
    G.photons = []; G.flashes = new Map();

    for (let i = 0; i < 120; i++) stepSim(G.sim);   // settle before the first paint

    startLoop();
  }

  // ----- pointer / wheel input -----
  const pointers = new Map(); let last = null, moved = 0, pinch = 0;
  // The long-press timer fires while the finger is still down, so the note opens
  // on the hold itself. Any roll, pinch or early release cancels it.
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

      if (pinch > 0) zoom(d / pinch);

      pinch = d; moved = 999; cancelPress();

      return;
    }

    if (last) {
      const dx = e.clientX - last.x, dy = e.clientY - last.y;
      moved += Math.abs(dx) + Math.abs(dy);
      // Roll: the axis is perpendicular to the drag, and the angle is the arc the
      // finger travelled divided by the radius — so the surface tracks the finger.
      const angle = Math.hypot(dx, dy) / Math.max(1, globeRadius());

      if (angle) {
        spinBy(rotationAbout(-dy, dx, 0, angle));

        if (++G.spins % 128 === 0) G.rot = orthonormalise(G.rot);
      }

      last = { x: e.clientX, y: e.clientY };
    }

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
  const onWheel = (e) => { e.preventDefault(); zoom(e.deltaY < 0 ? 1.1 : 0.9); };
  const onResize = () => { sizeCanvas(); };

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
    resetView() { autoFit(); startLoop(); },
    destroy() { stopLoop(); cancelPress(); unwireInput(); },
  };
}
