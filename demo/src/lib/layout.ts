import dagre from "@dagrejs/dagre";
import { ROOT, canEnter, flowOrder, links, node } from "./graph";

export interface LNode {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  /** synthetic entry / exit dots have no graph node behind them */
  port?: "in" | "out";
}

export interface LEdge {
  id: string;
  from: string;
  to: string;
  label?: "Yes" | "No";
  points: { x: number; y: number }[];
  back?: boolean;
  /** runs from the foot of one column to the head of the next */
  wrap?: boolean;
}

export interface Layout {
  scope: string;
  nodes: LNode[];
  byId: Record<string, LNode>;
  edges: LEdge[];
  box: { x: number; y: number; w: number; h: number };
}

export const CARD_W = 272;
const PORT = 18;
export const IN = "__in";
export const OUT = "__out";

/** Wrapped label lines, estimated conservatively so text is never cut mid-line. */
export function labelLines(id: string): number {
  const n = node(id);
  return Math.min(4, Math.max(1, Math.ceil(n.label.length / 31)));
}

/** Card height: tag row + title + label lines + optional "open" footer. */
export function cardHeight(id: string): number {
  return 68 + labelLines(id) * 19 + (canEnter(id) ? 30 : 0);
}

const cache = new Map<string, Layout>();

function finish(scope: string, nodes: LNode[], edges: LEdge[]): Layout {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const n of nodes) {
    x0 = Math.min(x0, n.x);
    y0 = Math.min(y0, n.y);
    x1 = Math.max(x1, n.x + n.w);
    y1 = Math.max(y1, n.y + n.h);
  }
  for (const e of edges)
    for (const p of e.points) {
      x0 = Math.min(x0, p.x);
      y0 = Math.min(y0, p.y);
      x1 = Math.max(x1, p.x);
      y1 = Math.max(y1, p.y);
    }
  const byId: Record<string, LNode> = {};
  for (const n of nodes) byId[n.id] = n;
  return { scope, nodes, byId, edges, box: { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } };
}

/** Level 0 is a hand-laid snake of stage cards so the whole program reads at a glance. */
export const STAGE_W = 256;
export const STAGE_H = 190;
function layoutRoot(cols: number): Layout {
  const stages = flowOrder(ROOT);
  const W = STAGE_W, H = STAGE_H, GX = 54, GY = 66;
  const nodes: LNode[] = [];
  stages.forEach((id, i) => {
    const r = Math.floor(i / cols), c = i % cols;
    nodes.push({ id, x: c * (W + GX), y: r * (H + GY), w: W, h: H });
  });
  const rows = Math.ceil(stages.length / cols);
  const lastCol = (stages.length - 1) % cols;
  nodes.push({ id: IN, port: "in", x: -GX - PORT, y: H / 2 - PORT / 2, w: PORT, h: PORT });
  nodes.push({
    id: OUT,
    port: "out",
    x: lastCol * (W + GX) + W + GX,
    y: (rows - 1) * (H + GY) + H / 2 - PORT / 2,
    w: PORT,
    h: PORT,
  });
  const by = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const edges: LEdge[] = [];
  const chain = [IN, ...stages, OUT];
  for (let i = 0; i < chain.length - 1; i++) {
    const a = by[chain[i]], b = by[chain[i + 1]];
    const sameRow = Math.abs(a.y + a.h / 2 - (b.y + b.h / 2)) < 1;
    let points;
    if (sameRow) {
      const y = a.y + a.h / 2;
      points = [{ x: a.x + a.w, y }, { x: b.x, y }];
    } else {
      // wrap: out of the bottom of the last card in a row, into the top of the first in the next
      const midY = a.y + a.h + GY / 2 + 4;
      points = [
        { x: a.x + a.w / 2, y: a.y + a.h + 10 },
        { x: a.x + a.w / 2, y: midY },
        { x: b.x + b.w / 2, y: midY },
        { x: b.x + b.w / 2, y: b.y },
      ];
    }
    edges.push({ id: `${a.id}>${b.id}`, from: a.id, to: b.id, points });
  }
  return finish(ROOT, nodes, edges);
}

function layoutFlow(scope: string): Layout {
  const g = new dagre.graphlib.Graph({ multigraph: true });
  g.setGraph({ rankdir: "TB", nodesep: 46, ranksep: 54, marginx: 0, marginy: 0 });
  g.setDefaultEdgeLabel(() => ({}));
  const kids = flowOrder(scope);
  const inScope = new Set(kids);
  for (const id of kids) g.setNode(id, { width: CARD_W, height: cardHeight(id) });

  const order = new Map(kids.map((id, i) => [id, i]));
  type E = { from: string; to: string; label?: "Yes" | "No" };
  const es: E[] = [];
  let needsOut = false;
  for (const id of kids) {
    const n = node(id);
    const out = links(id).filter((l) => inScope.has(l.to));
    for (const l of out) es.push({ from: id, to: l.to, label: l.label });
    if (n.type === "decision") {
      // a branch with no target falls through to whatever follows this block
      if (!n.yes) (es.push({ from: id, to: OUT, label: "Yes" }), (needsOut = true));
      if (!n.no) (es.push({ from: id, to: OUT, label: "No" }), (needsOut = true));
    } else if (out.length === 0 && n.type !== "end") {
      es.push({ from: id, to: OUT });
      needsOut = true;
    }
  }
  const entry = node(scope).entry ?? kids[0];
  g.setNode(IN, { width: PORT, height: PORT });
  es.unshift({ from: IN, to: entry });
  if (needsOut) g.setNode(OUT, { width: PORT, height: PORT });

  es.forEach((e, i) => {
    g.setEdge(e.from, e.to, { label: e.label ?? "", width: e.label ? 34 : 0, height: e.label ? 18 : 0, labelpos: "c" }, `e${i}`);
  });
  dagre.layout(g);

  const nodes: LNode[] = g.nodes().map((id) => {
    const v = g.node(id);
    return {
      id,
      x: v.x - v.width / 2,
      y: v.y - v.height / 2,
      w: v.width,
      h: v.height,
      port: id === IN ? "in" : id === OUT ? "out" : undefined,
    };
  });
  const edges: LEdge[] = es.map((e, i) => {
    const v = g.edge({ v: e.from, w: e.to, name: `e${i}` });
    const back =
      order.has(e.from) && order.has(e.to) && order.get(e.to)! <= order.get(e.from)!;
    return { id: `e${i}`, from: e.from, to: e.to, label: e.label, points: v.points, back };
  });
  return finish(scope, nodes, edges);
}

const COL_GAP = 76;

/**
 * A long chart is mostly a vertical chain, which wastes a wide viewport. Cut it into
 * side-by-side columns at places where exactly one edge passes, and route that edge
 * from the foot of one column to the head of the next.
 */
function wrap(l: Layout, vp: { w: number; h: number }): Layout {
  const real = l.nodes;
  const ys = [...new Set(real.map((n) => Math.round(n.y + n.h / 2)))].sort((a, b) => a - b);
  if (ys.length < 4) return l;
  const rankOf = new Map(real.map((n) => [n.id, ys.indexOf(Math.round(n.y + n.h / 2))]));
  const top = ys.map((_, r) => Math.min(...real.filter((n) => rankOf.get(n.id) === r).map((n) => n.y)));
  const bottom = ys.map((_, r) => Math.max(...real.filter((n) => rankOf.get(n.id) === r).map((n) => n.y + n.h)));

  // gap g sits between rank g and g + 1
  const bridge: (LEdge | null)[] = [];
  for (let g = 0; g < ys.length - 1; g++) {
    const crossing = l.edges.filter((e) => {
      const a = rankOf.get(e.from)!, b = rankOf.get(e.to)!;
      return Math.min(a, b) <= g && Math.max(a, b) > g;
    });
    const only = crossing.length === 1 ? crossing[0] : null;
    bridge.push(only && rankOf.get(only.from) === g && rankOf.get(only.to) === g + 1 ? only : null);
  }

  const extent = (from: number, to: number) => {
    let x0 = Infinity, x1 = -Infinity;
    for (const n of real) {
      const r = rankOf.get(n.id)!;
      if (r >= from && r <= to) (x0 = Math.min(x0, n.x), (x1 = Math.max(x1, n.x + n.w)));
    }
    for (const e of l.edges) {
      const a = rankOf.get(e.from)!, b = rankOf.get(e.to)!;
      if (Math.min(a, b) >= from && Math.max(a, b) <= to) for (const p of e.points) (x0 = Math.min(x0, p.x), (x1 = Math.max(x1, p.x)));
    }
    return { x0, x1, y0: top[from], y1: bottom[to] };
  };

  const availW = vp.w - 104, availH = vp.h - 104;
  let best: { cuts: number[]; k: number } = { cuts: [], k: Math.min(availW / l.box.w, availH / l.box.h) };
  for (let cols = 2; cols <= 6 && best.k < 1; cols++) {
    const cuts: number[] = [];
    for (let i = 1; i < cols; i++) {
      const ideal = l.box.y + (l.box.h * i) / cols;
      let pick = -1, dist = Infinity;
      for (let g = (cuts[cuts.length - 1] ?? -1) + 1; g < bridge.length; g++) {
        if (!bridge[g]) continue;
        const d = Math.abs((bottom[g] + top[g + 1]) / 2 - ideal);
        if (d < dist) (pick = g), (dist = d);
      }
      if (pick >= 0) cuts.push(pick);
    }
    if (cuts.length !== cols - 1) break;
    const spans = [-1, ...cuts].map((c, i) => extent(c + 1, i < cuts.length ? cuts[i] : ys.length - 1));
    const w = spans.reduce((sum, e) => sum + (e.x1 - e.x0), 0) + COL_GAP * cuts.length;
    const h = Math.max(...spans.map((e) => e.y1 - e.y0)) + 30;
    const k = Math.min(availW / w, availH / h);
    if (k > best.k + 0.04) best = { cuts, k };
  }
  if (!best.cuts.length) return l;

  const starts = [0, ...best.cuts.map((c) => c + 1)];
  const colOf = (rank: number) => starts.filter((s) => s <= rank).length - 1;
  const shift: { dx: number; dy: number; right: number }[] = [];
  let x = 0;
  starts.forEach((from, i) => {
    const e = extent(from, i + 1 < starts.length ? starts[i + 1] - 1 : ys.length - 1);
    shift.push({ dx: x - e.x0, dy: -e.y0, right: x + (e.x1 - e.x0) });
    x += e.x1 - e.x0 + COL_GAP;
  });
  const nodes = real.map((n) => {
    const s = shift[colOf(rankOf.get(n.id)!)];
    return { ...n, x: n.x + s.dx, y: n.y + s.dy };
  });
  const by = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const bridges = new Set(best.cuts.map((c) => bridge[c]!.id));
  const edges = l.edges.map((e) => {
    if (bridges.has(e.id)) {
      const a = by[e.from], b = by[e.to];
      const gutter = shift[colOf(rankOf.get(e.from)!)].right + COL_GAP / 2;
      const ax = a.x + a.w / 2, bx = b.x + b.w / 2, low = a.y + a.h + 26, high = b.y - 26;
      return { ...e, points: [{ x: ax, y: a.y + a.h }, { x: ax, y: low }, { x: gutter, y: low }, { x: gutter, y: high }, { x: bx, y: high }, { x: bx, y: b.y }], wrap: true };
    }
    const s = shift[colOf(rankOf.get(e.from)!)];
    return { ...e, points: e.points.map((p) => ({ x: p.x + s.dx, y: p.y + s.dy })) };
  });
  return finish(l.scope, nodes, edges);
}

/** The top level gets the hand-laid grid only while it is a plain sequence of steps. */
export const rootIsChain = () => node(ROOT).children.every((c) => node(c).type !== "decision") && node(ROOT).children.length <= 9;

export function layoutOf(scope: string, rootCols = 4, vp?: { w: number; h: number }): Layout {
  const bucket = vp && scope !== ROOT ? `${Math.round(vp.w / 60)}x${Math.round(vp.h / 60)}` : "";
  const key = scope === ROOT ? `${scope}:${rootCols}` : `${scope}:${bucket}`;
  let hit = cache.get(key);
  if (!hit) {
    hit = rootIsChain() ? (scope === ROOT ? layoutRoot(rootCols) : layoutFlow(scope)) : layoutFlow(scope);
    if (vp && vp.w > 0 && !(scope === ROOT && rootIsChain())) hit = wrap(hit, vp);
    cache.set(key, hit);
  }
  return hit;
}

/** Smooth path through dagre's control points. */
export function pathOf(points: { x: number; y: number }[], r = 14): string {
  if (points.length < 2) return "";
  if (points.length === 2)
    return `M${points[0].x},${points[0].y}L${points[1].x},${points[1].y}`;
  let d = `M${points[0].x},${points[0].y}`;
  for (let i = 1; i < points.length - 1; i++) {
    const p0 = points[i - 1], p1 = points[i], p2 = points[i + 1];
    const d1 = Math.hypot(p1.x - p0.x, p1.y - p0.y) || 1;
    const d2 = Math.hypot(p2.x - p1.x, p2.y - p1.y) || 1;
    const r1 = Math.min(r, d1 / 2), r2 = Math.min(r, d2 / 2);
    const a = { x: p1.x - ((p1.x - p0.x) / d1) * r1, y: p1.y - ((p1.y - p0.y) / d1) * r1 };
    const b = { x: p1.x + ((p2.x - p1.x) / d2) * r2, y: p1.y + ((p2.y - p1.y) / d2) * r2 };
    d += `L${a.x},${a.y}Q${p1.x},${p1.y} ${b.x},${b.y}`;
  }
  const last = points[points.length - 1];
  return d + `L${last.x},${last.y}`;
}
