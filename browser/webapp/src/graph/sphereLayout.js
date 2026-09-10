// Force layout for notes on the surface of a unit sphere.
//
// Pure maths, no DOM: the engine renders whatever this produces, and the layout
// can be measured on its own. Linked notes are grouped: the graph is split into
// communities (label propagation), each community is seeded into its own cap of
// the sphere with linked notes next to each other, and the forces keep a group
// tight (short springs, cohesion to its centre, gentle repulsion inside it) while
// pushing different groups apart. Links therefore stay short and mostly inside a
// group, so they cross less and fewer unrelated notes sit on top of them.

// Below this the layout is settled and stops moving entirely.
export const ALPHA_REST = 0.004;

const GOLDEN = Math.PI * (3 - Math.sqrt(5));

// Force constants, chosen by a sweep that scored link crossings and notes lying
// on links across random and clustered graphs, while keeping notes spread over
// the whole globe and no closer together than before. Repulsion between groups
// is stronger than inside one, which opens clear space between clusters; short
// stiff springs and cohesion to the group's centre keep a group one tight patch.
const REPEL_OUT = 0.12, REPEL_IN = 0.05;
const SPRING = 0.2, LINK_CHORD = 0.18;
const COHESION = 0.07;
const DAMP = 0.82, DECAY = 0.978;

// Fraction of the sphere's area handed to the groups' seed caps overall; the rest
// is left as gaps between groups.
const CAP_SHARE = 0.75;

function cross(a, b) {
  return { x: a.y * b.z - a.z * b.y, y: a.z * b.x - a.x * b.z, z: a.x * b.y - a.y * b.x };
}

function normalise(v) {
  const len = Math.hypot(v.x, v.y, v.z) || 1;

  return { x: v.x / len, y: v.y / len, z: v.z / len };
}

// Evenly spread points; the first one faces the viewer (+z), so the biggest group
// is what you see on opening the map.
function spiralPoint(count, index) {
  const z = count === 1 ? 1 : 1 - (index / (count - 1)) * 2;
  const r = Math.sqrt(Math.max(0, 1 - z * z));
  const theta = GOLDEN * index;

  return { x: Math.cos(theta) * r, y: Math.sin(theta) * r, z };
}

// Two unit vectors perpendicular to `c`, spanning the tangent plane there.
function tangentBasis(c) {
  const helper = Math.abs(c.x) < 0.9 ? { x: 1, y: 0, z: 0 } : { x: 0, y: 1, z: 0 };
  const u = normalise(cross(c, helper));

  return { u, v: cross(c, u) };
}

// The point `alpha` radians from `c`, in direction `phi` around it.
function capPoint(c, basis, alpha, phi) {
  const ca = Math.cos(alpha), sa = Math.sin(alpha);
  const cp = Math.cos(phi), sp = Math.sin(phi);

  return normalise({
    x: ca * c.x + sa * (cp * basis.u.x + sp * basis.v.x),
    y: ca * c.y + sa * (cp * basis.u.y + sp * basis.v.y),
    z: ca * c.z + sa * (cp * basis.u.z + sp * basis.v.z),
  });
}

function adjacency(ids, edges) {
  const adj = new Map(ids.map((id) => [id, []]));

  for (const e of edges) {
    adj.get(e.source).push(e.target);
    adj.get(e.target).push(e.source);
  }

  return adj;
}

// Label propagation: every note repeatedly adopts the label most common among its
// neighbours, so densely linked notes converge on a shared label. Hubs go first
// and ties keep the current label (else the smallest), which makes it
// deterministic. Returns groups of ids, largest first.
export function findCommunities(ids, edges) {
  const adj = adjacency(ids, edges);
  const label = new Map(ids.map((id) => [id, id]));
  const order = [...ids].sort((a, b) => adj.get(b).length - adj.get(a).length || a - b);

  for (let pass = 0; pass < 20; pass++) {
    let changed = false;

    for (const id of order) {
      const tally = new Map();

      for (const nb of adj.get(id)) tally.set(label.get(nb), (tally.get(label.get(nb)) || 0) + 1);

      if (!tally.size) continue;

      const current = label.get(id);
      let best = current, bestCount = tally.get(current) || 0;

      for (const [l, count] of tally) {
        if (count > bestCount || (count === bestCount && best !== current && l < best)) {
          best = l;
          bestCount = count;
        }
      }

      if (best !== current) {
        label.set(id, best);
        changed = true;
      }
    }

    if (!changed) break;
  }

  const groups = new Map();

  for (const id of ids) {
    if (!groups.has(label.get(id))) groups.set(label.get(id), []);

    groups.get(label.get(id)).push(id);
  }

  return [...groups.values()].sort((a, b) => b.length - a.length || a[0] - b[0]);
}

// A group's members in breadth-first order from its best-connected note, so
// consecutive members — which are seeded next to each other — are linked.
function bfsOrder(members, adj) {
  const inGroup = new Set(members);
  const start = [...members].sort((a, b) => adj.get(b).length - adj.get(a).length || a - b);
  const seen = new Set(), order = [];

  for (const root of start) {
    if (seen.has(root)) continue;

    const queue = [root];
    seen.add(root);

    while (queue.length) {
      const id = queue.shift();
      order.push(id);

      for (const nb of adj.get(id)) {
        if (!inGroup.has(nb) || seen.has(nb)) continue;

        seen.add(nb);
        queue.push(nb);
      }
    }
  }

  return order;
}

// Seed every group into its own cap: group centres are spread evenly (largest
// facing the viewer), each cap's area is proportional to its group's size, and
// members fill it as a sunflower in BFS order — hub in the middle, neighbours
// around it.
function seedPositions(ids, edges, groups) {
  const adj = adjacency(ids, edges);
  const total = ids.length, placed = new Map();

  groups.forEach((members, g) => {
    const centre = spiralPoint(groups.length, g);
    const basis = tangentBasis(centre);
    const share = Math.min(0.5, (CAP_SHARE * members.length) / total);
    const capRadius = Math.acos(1 - 2 * share);
    const order = bfsOrder(members, adj);

    order.forEach((id, j) => {
      const alpha = capRadius * Math.sqrt((j + 0.5) / order.length);
      placed.set(id, capPoint(centre, basis, alpha, j * GOLDEN));
    });
  });

  return placed;
}

export function buildSim(data) {
  const ids = data.nodes.map((n) => n.id);
  const known = new Set(ids);
  const links = (data.edges || []).filter((e) => known.has(e.source) && known.has(e.target));
  const groups = findCommunities(ids, links);
  const seeds = seedPositions(ids, links, groups);
  const groupOf = new Map();

  groups.forEach((members, g) => members.forEach((id) => groupOf.set(id, g)));

  const nodes = data.nodes.map((n) => ({
    ...n,
    ...seeds.get(n.id),
    vx: 0, vy: 0, vz: 0,
    group: groupOf.get(n.id),
  }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges = links.map((e) => ({ a: byId.get(e.source), b: byId.get(e.target) }));

  return { nodes, edges, groups: groups.length, alpha: 1 };
}

// Where each group's centre currently is on the sphere.
function groupCentres(sim) {
  const sums = Array.from({ length: sim.groups }, () => ({ x: 0, y: 0, z: 0 }));

  for (const n of sim.nodes) {
    const s = sums[n.group];
    s.x += n.x; s.y += n.y; s.z += n.z;
  }

  return sums.map(normalise);
}

// Forces act on the chord between two nodes; after integrating, every node is
// pushed back onto the unit sphere and its velocity flattened into the tangent
// plane, so everything slides along the surface instead of leaving it.
export function stepSim(sim) {
  const nodes = sim.nodes, a = sim.alpha;

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

      const repel = ni.group === nj.group ? REPEL_IN : REPEL_OUT;
      const inv = 1 / Math.sqrt(d2), f = repel / Math.max(d2, 0.02);
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

  const centres = groupCentres(sim);

  for (const n of nodes) {
    const c = centres[n.group];
    n.vx += (c.x - n.x) * COHESION;
    n.vy += (c.y - n.y) * COHESION;
    n.vz += (c.z - n.z) * COHESION;
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

  sim.alpha = a < ALPHA_REST ? 0 : a * DECAY;
}
