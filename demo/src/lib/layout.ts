import dagre from "@dagrejs/dagre";
import { canEnter, flowOrder, links, node } from "./graph";

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
  label?: string;
  points: { x: number; y: number }[];
  /** jumps back to an earlier step: a loop */
  back?: boolean;
  /** goes around a step that runs only under a condition */
  skip?: boolean;
}

export interface Layout {
  scope: string;
  nodes: LNode[];
  byId: Record<string, LNode>;
  edges: LEdge[];
  box: { x: number; y: number; w: number; h: number };
}

export const CARD_W = 236;
const PORT = 18;
export const IN = "__in";
export const OUT = "__out";

/** Wrapped label lines, estimated conservatively so text is never cut mid-line. */
export function labelLines(id: string): number {
  return Math.min(4, Math.max(1, Math.ceil(node(id).label.length / 27)));
}

/** Card height: tag row + title + label lines + optional footer with a miniature of the chart inside. */
export function cardHeight(id: string): number {
  return 68 + labelLines(id) * 19 + (canEnter(id) ? 50 : 0);
}

const cache = new Map<string, Layout>();

/**
 * Every chart is drawn the same way: a left-to-right layered graph. Sequence runs
 * along the row, branches fan out vertically, loops come back underneath, and a step
 * that only runs under a condition gets an edge that goes around it.
 */
function build(scope: string): Layout {
  const g = new dagre.graphlib.Graph({ multigraph: true });
  g.setGraph({ rankdir: "LR", nodesep: 34, ranksep: 62, marginx: 0, marginy: 0 });
  g.setDefaultEdgeLabel(() => ({}));
  const kids = flowOrder(scope);
  const inScope = new Set(kids);
  for (const id of kids) g.setNode(id, { width: CARD_W, height: cardHeight(id) });

  const order = new Map(kids.map((id, i) => [id, i]));
  type E = { from: string; to: string; label?: string; skip?: boolean };
  const es: E[] = [];
  let needsOut = false;
  const preds = new Map<string, string[]>();
  for (const id of kids) {
    const n = node(id);
    const out = links(id).filter((l) => inScope.has(l.to));
    for (const l of out) {
      es.push({ from: id, to: l.to, label: l.label });
      (preds.get(l.to) ?? preds.set(l.to, []).get(l.to)!).push(id);
    }
    if (n.type === "decision") {
      // a branch with no target in this chart leaves it
      if (!n.yes || !inScope.has(n.yes)) (es.push({ from: id, to: OUT, label: "Yes" }), (needsOut = true));
      if (!n.no || !inScope.has(n.no)) (es.push({ from: id, to: OUT, label: "No" }), (needsOut = true));
    } else if (out.length === 0) {
      es.push({ from: id, to: OUT });
      needsOut = true;
    }
  }
  const entry = node(scope).entry ?? kids[0];
  g.setNode(IN, { width: PORT, height: PORT });
  es.unshift({ from: IN, to: entry });
  (preds.get(entry) ?? preds.set(entry, []).get(entry)!).push(IN);

  // a guarded step can be skipped: draw the way around it
  for (const id of kids) {
    const n = node(id);
    if (!n.guard || n.type === "decision") continue;
    const after = n.next && inScope.has(n.next) ? n.next : OUT;
    if (after === OUT) needsOut = true;
    for (const p of preds.get(id) ?? []) {
      if (order.has(p) && order.get(p)! >= order.get(id)!) continue;
      if (!es.some((e) => e.from === p && e.to === after)) es.push({ from: p, to: after, skip: true, label: "skip" });
    }
  }
  if (needsOut) g.setNode(OUT, { width: PORT, height: PORT });

  es.forEach((e, i) => {
    const w = e.label ? Math.max(30, e.label.length * 7 + 14) : 0;
    g.setEdge(e.from, e.to, { label: e.label ?? "", width: w, height: e.label ? 18 : 0, labelpos: "c" }, `e${i}`);
  });
  dagre.layout(g);

  const nodes: LNode[] = g.nodes().map((id) => {
    const v = g.node(id);
    return { id, x: v.x - v.width / 2, y: v.y - v.height / 2, w: v.width, h: v.height, port: id === IN ? "in" : id === OUT ? "out" : undefined };
  });
  const edges: LEdge[] = es.map((e, i) => {
    const v = g.edge({ v: e.from, w: e.to, name: `e${i}` });
    const back = order.has(e.from) && order.has(e.to) && order.get(e.to)! <= order.get(e.from)!;
    return { id: `e${i}`, from: e.from, to: e.to, label: e.label, points: v.points, back, skip: e.skip };
  });

  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const grow = (x: number, y: number) => {
    x0 = Math.min(x0, x);
    y0 = Math.min(y0, y);
    x1 = Math.max(x1, x);
    y1 = Math.max(y1, y);
  };
  for (const n of nodes) (grow(n.x, n.y), grow(n.x + n.w, n.y + n.h));
  for (const e of edges) for (const p of e.points) grow(p.x, p.y);
  const byId: Record<string, LNode> = {};
  for (const n of nodes) byId[n.id] = n;
  return { scope, nodes, byId, edges, box: { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } };
}

export function layoutOf(scope: string): Layout {
  let hit = cache.get(scope);
  if (!hit) cache.set(scope, (hit = build(scope)));
  return hit;
}

/** Smooth path through dagre's control points. */
export function pathOf(points: { x: number; y: number }[], r = 16): string {
  if (points.length < 2) return "";
  if (points.length === 2) return `M${points[0].x},${points[0].y}L${points[1].x},${points[1].y}`;
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
