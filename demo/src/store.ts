import { useSyncExternalStore } from "react";
import { ROOT, chartFor, displayOf, enterTarget, hasNode, isScope, lineage, parentScope } from "./lib/graph";

export type DockTab = "source" | "ask";

export interface State {
  scope: string;
  selected: string | null;
  /** whether the floating panel is shown for the selected node */
  panel: boolean;
  hover: string | null;
  /** ordered node ids of the highlighted execution path */
  highlight: string[];
  dock: DockTab | null;
  /** bumped to ask the canvas to bring `selected` into view */
  focusTick: number;
  /** true while an agent answer is moving the diagram */
  driving: boolean;
  touched: boolean;
}

const wide = typeof window !== "undefined" && window.innerWidth >= 1500;

let state: State = {
  scope: ROOT,
  selected: null,
  panel: true,
  hover: null,
  highlight: [],
  dock: wide ? "source" : null,
  focusTick: 0,
  driving: false,
  touched: false,
};

const listeners = new Set<() => void>();
export const getState = () => state;
export function set(patch: Partial<State>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}
export function useStore<T>(pick: (s: State) => T): T {
  return useSyncExternalStore(
    (l) => (listeners.add(l), () => listeners.delete(l)),
    () => pick(state),
  );
}

const reduced =
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
/** Scale for animation durations: near zero when the visitor prefers reduced motion. */
export const motion = () => (reduced ? 0.01 : 1);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const waiters: (() => void)[] = [];
/** The canvas calls this when it has finished travelling to the scope in the store. */
export function arrived() {
  waiters.splice(0).forEach((w) => w());
}

/** Ask the canvas to travel to a scope, and wait until it is there. */
export async function goTo(target: string, keepSelection = false): Promise<void> {
  const scope = enterTarget(target) ?? displayOf(target).scope;
  if (scope === state.scope) return;
  set({ scope, ...(keepSelection ? {} : { selected: null }), touched: true });
  await Promise.race([new Promise<void>((r) => waiters.push(r)), sleep(6000)]);
}

export const openNode = (id: string) => {
  const t = enterTarget(id);
  if (t) void goTo(t);
};

export const goUp = () => {
  const p = parentScope(state.scope);
  if (p) void goTo(p);
};

export function select(id: string | null) {
  set({ selected: id, panel: true, touched: true });
}

/** Show a node: travel to the chart that draws it, select it and bring it into view. */
export async function focusNode(id: string, panel = true): Promise<void> {
  if (!hasNode(id)) return;
  const { scope, shown } = displayOf(id);
  if (scope !== state.scope) await goTo(scope, true);
  set({ selected: shown, panel, focusTick: state.focusTick + 1 });
  await sleep(reduced ? 1 : 420);
}

export function setHighlight(ids: string[]) {
  set({ highlight: ids.filter(hasNode) });
}

/** ids of every highlighted node plus all of their ancestors, with path order */
export function highlightOrder(ids: string[]): Map<string, number> {
  const out = new Map<string, number>();
  ids.forEach((id, i) => {
    for (const a of lineage(id)) if (!out.has(a)) out.set(a, i);
  });
  return out;
}

export type Action =
  | { tool: "focus_node"; id: string }
  | { tool: "zoom_to_level"; id: string }
  | { tool: "highlight_path"; ids: string[] };

/** The three UI tools an answer can call. */
export async function runAction(a: Action, panel = true): Promise<void> {
  if (a.tool === "zoom_to_level") {
    const id = chartFor(a.id);
    if (hasNode(id)) await goTo(isScope(id) ? id : (enterTarget(id) ?? displayOf(id).scope), true);
  } else if (a.tool === "focus_node") {
    await focusNode(a.id, panel);
  } else {
    setHighlight(a.ids);
    await sleep(reduced ? 1 : 500);
  }
}
