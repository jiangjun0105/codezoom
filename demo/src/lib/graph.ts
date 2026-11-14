import raw from "../data/graph.json";

export type NodeType = "start" | "end" | "action" | "call" | "decision";

export interface GNode {
  id: string;
  type: NodeType;
  kind: string;
  label: string;
  title: string;
  /** one-line version of the label, for the top-level cards */
  parent: string | null;
  children: string[];
  entry?: string;
  next?: string;
  yes?: string;
  no?: string;
  callee?: string;
  fn: string;
  lines?: [number, number];
  code?: string;
  /** functions whose call step was expanded into this chart */
  via?: string[];
  /** a group made by the abstraction pass, and who named it */
  generated?: boolean;
  namedBy?: "model" | "fallback";
  authored?: boolean;
  labelRepaired?: boolean;
  pipelineSummary?: string;
}

export interface GFunction {
  uri: string;
  name: string;
  module: string;
  code?: string;
  fileLine?: number;
  summary?: string;
  calls?: string[];
  calledBy?: string[];
  chart?: string;
}

interface Graph {
  meta: {
    repo: string;
    version: string;
    entry: string;
    root: string;
    entryFn: string;
    nodeCount: number;
    functionCount: number;
    chartedFunctions: number;
  };
  nodes: Record<string, GNode>;
  functions: Record<string, GFunction>;
  /** ids of steps the abstraction pass folded away -> where their content went */
  aliases: Record<string, string>;
}

export const graph = raw as unknown as Graph;
export const ROOT = graph.meta.root;

/** Ids from the 2023 dumps may name a step that was folded into another; follow it. */
export const canon = (id: string): string => (id in graph.nodes ? id : (graph.aliases[id] ?? id));
export const node = (id: string): GNode => graph.nodes[canon(id)];
export const hasNode = (id: string) => canon(id) in graph.nodes;
export const fnInfo = (uri: string): GFunction | undefined => graph.functions[uri];

/** Ancestors from the root down to (and including) the node. */
export function lineage(id: string): string[] {
  const out: string[] = [];
  let cur: string | null = canon(id);
  while (cur && graph.nodes[cur]) {
    out.push(cur);
    cur = graph.nodes[cur].parent;
  }
  return out.reverse();
}

const PASS_KINDS = new Set(["wrapper", "call_wrapper"]);

/**
 * The scope you land in when you open a node, or null when there is nothing worth
 * opening. `x = f()` wrappers hold just the call and a "store the result" node, so
 * they open straight into the callee instead of a two-node chart.
 */
export function enterTarget(id: string): string | null {
  id = canon(id);
  const n = graph.nodes[id];
  if (!n || n.children.length === 0) return null;
  if (PASS_KINDS.has(n.kind)) {
    const containers = n.children.filter((c) => graph.nodes[c].children.length > 0);
    if (n.children.length <= 2) {
      if (containers.length === 1) return enterTarget(containers[0]);
      if (containers.length === 0) return null;
    }
  }
  return id;
}

export const isScope = (id: string) => enterTarget(id) === id;
export const canEnter = (id: string) => enterTarget(id) !== null;

/** The scope whose chart shows this node, and the node that stands for it there. */
export function displayOf(id: string): { scope: string; shown: string } {
  let shown = canon(id);
  let p = graph.nodes[shown]?.parent;
  while (p && !isScope(p)) {
    shown = p;
    p = graph.nodes[shown].parent;
  }
  return { scope: p ?? ROOT, shown };
}

export function parentScope(scope: string): string | null {
  if (scope === ROOT) return null;
  return displayOf(scope).scope;
}

/** Scopes from the root down to this one. */
export function scopeTrail(scope: string): string[] {
  const out = [scope];
  let cur = parentScope(scope);
  while (cur) {
    out.push(cur);
    cur = parentScope(cur);
  }
  return out.reverse();
}

/** The node drawn in `scope`'s chart that contains `id` (or is it), if any. */
export function shownIn(scope: string, id: string): string | null {
  const line = lineage(id);
  const i = line.indexOf(scope);
  return i >= 0 && i < line.length - 1 ? line[i + 1] : null;
}

/** The function whose source a scope's chart is drawn from. */
export function scopeFn(scope: string): string {
  const share = new Map<string, number>();
  for (const c of node(scope).children) share.set(node(c).fn, (share.get(node(c).fn) ?? 0) + leafCount(c));
  return [...share.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? node(scope).fn;
}

/** Breadcrumb: the scopes on the way down, plus any stage that was passed through. */
export function crumbs(scope: string): { id: string; title: string; target: string }[] {
  return lineage(scope)
    .filter((id) => isScope(id))
    .map((id) => ({ id, title: node(id).title, target: enterTarget(id) ?? id }));
}

export const shortFn = (uri: string) => uri.slice(uri.lastIndexOf("/") + 1);
export const modulePath = (uri: string) =>
  uri.replace(/^\//, "").split("/")[0].replace(/\./g, "/") + ".py";

/** Outgoing links of a node that stay inside its scope. */
export function links(id: string): { to: string; label?: "Yes" | "No" }[] {
  const n = node(id);
  const out: { to: string; label?: "Yes" | "No" }[] = [];
  if (n.next) out.push({ to: n.next });
  if (n.yes) out.push({ to: n.yes, label: "Yes" });
  if (n.no) out.push({ to: n.no, label: "No" });
  return out;
}

/** Children of a scope in execution order (breadth-first from the entry). */
export function flowOrder(scope: string): string[] {
  const n = node(scope);
  const kids = new Set(n.children);
  const seen = new Set<string>();
  const out: string[] = [];
  const queue = [n.entry ?? n.children[0]];
  while (queue.length) {
    const cur = queue.shift()!;
    if (!cur || seen.has(cur) || !kids.has(cur)) continue;
    seen.add(cur);
    out.push(cur);
    for (const l of links(cur)) queue.push(l.to);
  }
  for (const k of n.children) if (!seen.has(k)) out.push(k);
  return out;
}

/** Number of leaf statements under a node. */
const sizeCache = new Map<string, number>();
export function leafCount(id: string): number {
  const hit = sizeCache.get(id);
  if (hit !== undefined) return hit;
  const n = node(id);
  const v = n.children.length ? n.children.reduce((s, c) => s + leafCount(c), 0) : 1;
  sizeCache.set(id, v);
  return v;
}

export function depthBelow(id: string): number {
  const n = node(id);
  return n.children.length ? 1 + Math.max(...n.children.map(depthBelow)) : 0;
}

/** Every call site of a function that appears in the chart. */
export function callSites(uri: string): string[] {
  return Object.values(graph.nodes)
    .filter((n) => n.callee === uri)
    .map((n) => n.id);
}
