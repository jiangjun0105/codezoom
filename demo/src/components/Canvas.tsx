import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  ROOT,
  canEnter,
  leafCount,
  lineage,
  node,
  parentScope,
  shownIn,
  type GNode,
} from "../lib/graph";
import { IN, OUT, labelLines, layoutOf, pathOf, type LEdge, type Layout } from "../lib/layout";
import {
  getState,
  goUp,
  highlightOrder,
  openNode,
  select,
  set,
  setHighlight,
  transitionMs,
  useStore,
} from "../store";
import { clearThread } from "../lib/ask";
import { NodePanel } from "./NodePanel";

interface Cam {
  x: number;
  y: number;
  k: number;
}
interface Size {
  w: number;
  h: number;
}

const PAD = 52;
const PANEL_W = 352;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const ramp = (t: number, a: number, b: number) => clamp((t - a) / (b - a), 0, 1);

/** Camera that shows a chart: fitted when it is small, readable and top-aligned when it is not. */
function camFor(l: Layout, vp: Size, focus?: { x: number; y: number; w: number; h: number }): Cam {
  const pad = l.scope === ROOT ? 34 : PAD;
  const fit = Math.min((vp.w - pad * 2) / l.box.w, (vp.h - pad * 2 - (l.scope === ROOT ? 30 : 0)) / l.box.h);
  const k = clamp(fit, l.scope === ROOT ? 0.3 : 0.7, l.scope === ROOT ? 1.25 : 1.08);
  const anchor = l.byId[IN] ?? null;
  const fitsW = l.box.w * k <= vp.w - pad * 2 + 1;
  const fitsH = l.box.h * k <= vp.h - pad * 2 + 1;
  let x = fitsW || !anchor
    ? vp.w / 2 - k * (l.box.x + l.box.w / 2)
    : vp.w / 2 - k * (anchor.x + anchor.w / 2);
  let y = fitsH ? vp.h / 2 - k * (l.box.y + l.box.h / 2) - (l.scope === ROOT ? 12 : 0) : pad - k * l.box.y;
  if (focus) {
    if (!fitsH)
      y = clamp(vp.h / 2 - k * (focus.y + focus.h / 2), vp.h - pad - k * (l.box.y + l.box.h), pad - k * l.box.y);
    if (!fitsW)
      x = clamp(vp.w / 2 - k * (focus.x + focus.w / 2), vp.w - pad - k * (l.box.x + l.box.w), pad - k * l.box.x);
  }
  return { x, y, k };
}

/** Where a child chart sits inside the node that stands for it in the parent chart. */
function nest(parent: Layout, child: Layout) {
  const shown = shownIn(parent.scope, child.scope);
  const r = shown ? parent.byId[shown] : null;
  if (!r) return null;
  const m = Math.min(r.w / child.box.w, r.h / child.box.h) * 0.9;
  return {
    rect: r,
    m,
    tx: r.x + r.w / 2 - m * (child.box.x + child.box.w / 2),
    ty: r.y + r.h / 2 - m * (child.box.y + child.box.h / 2),
  };
}

const TAGS: Record<string, string> = {
  if_wrapper: "Branch",
  for_wrapper: "Loop",
  while_wrapper: "Loop",
  try_wrapper: "Try",
  with_wrapper: "With",
  nodes_wrapper: "Block",
  check_value: "If",
  for_check: "Loop test",
  except: "Except",
};
export function tagOf(n: GNode): string {
  if (n.type === "call") return "Call";
  return TAGS[n.kind] ?? (n.type === "decision" ? "If" : "Action");
}
export function toneOf(n: GNode): string {
  if (n.type === "call") return "call";
  if (n.type === "decision") return "decision";
  if (n.kind === "for_wrapper" || n.kind === "while_wrapper") return "loop";
  if (n.kind === "stage") return "stage";
  return "action";
}
export const linesOf = (n: GNode) =>
  n.lines ? (n.lines[0] === n.lines[1] ? `L${n.lines[0]}` : `L${n.lines[0]}–${n.lines[1]}`) : "";

/** Edges on the highlighted path: direct ones, plus the shortest route between consecutive stops. */
function litEdges(l: Layout, order: Map<string, number>): Set<string> {
  const stops = l.nodes
    .filter((n) => order.has(n.id))
    .sort((a, b) => order.get(a.id)! - order.get(b.id)!)
    .map((n) => n.id);
  const lit = new Set<string>();
  const out = new Map<string, LEdge[]>();
  for (const e of l.edges) (out.get(e.from) ?? out.set(e.from, []).get(e.from)!).push(e);
  for (let i = 0; i < stops.length - 1; i++) {
    const from = stops[i], to = stops[i + 1];
    const prev = new Map<string, LEdge>();
    const queue = [from];
    const seen = new Set([from]);
    while (queue.length) {
      const cur = queue.shift()!;
      if (cur === to) break;
      for (const e of out.get(cur) ?? []) {
        if (seen.has(e.to) || e.to === OUT) continue;
        seen.add(e.to);
        prev.set(e.to, e);
        queue.push(e.to);
      }
    }
    let cur = to;
    while (prev.has(cur)) {
      const e = prev.get(cur)!;
      lit.add(e.id);
      cur = e.from;
    }
  }
  return lit;
}

const Card = memo(function Card(props: {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  index: number;
  selected: boolean;
  hovered: boolean;
  lit: number | null;
  dim: boolean;
}) {
  const n = node(props.id);
  const style = {
    left: props.x,
    top: props.y,
    width: props.w,
    height: props.h,
    "--i": props.index,
    "--hl": props.lit ?? 0,
    "--lines": n.kind === "stage" ? 2 : labelLines(n.id),
  } as React.CSSProperties;
  const cls = [
    "card",
    `tone-${toneOf(n)}`,
    props.selected && "is-selected",
    props.hovered && "is-hover",
    props.lit !== null && "is-lit",
    props.dim && "is-dim",
  ]
    .filter(Boolean)
    .join(" ");

  if (n.type === "start" || n.type === "end") {
    return (
      <div className={`${cls} pill`} style={style} data-id={n.id}>
        <span className={`dot ${n.type}`} />
        <span className="pill-title">{n.title}</span>
        <span className="pill-sub">{n.label}</span>
      </div>
    );
  }
  const enterable = canEnter(n.id);
  const stage = n.kind === "stage";
  const stageNo = stage ? node(ROOT).children.filter((c) => node(c).kind === "stage").indexOf(n.id) + 1 : 0;
  return (
    <div className={`${cls}${enterable ? " is-deep" : ""}`} style={style} data-id={n.id} tabIndex={0} role="button" aria-label={n.label}>
      <div className="card-tag">
        <span className="glyph" />
        <span>{stage ? `Step ${stageNo}` : tagOf(n)}</span>
        <span className="card-lines">{linesOf(n)}</span>
      </div>
      <div className={stage ? "card-title stage-title" : "card-title"}>{n.title}</div>
      <div className="card-label">{stage ? (n.blurb ?? n.label) : n.label}</div>
      {enterable && (
        <button className="card-open" data-open={n.id} tabIndex={-1}>
          <span>Zoom in</span>
          <span className="card-count">{leafCount(n.id)} statements</span>
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
            <path d="M4 2.5 7.5 6 4 9.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}
    </div>
  );
});

const ScopeLayer = memo(function ScopeLayer(props: {
  layout: Layout;
  selected: string | null;
  hover: string | null;
  highlight: string[];
  portal: string | null;
}) {
  const { layout: l, selected, hover, highlight } = props;
  const order = useMemo(() => highlightOrder(highlight), [highlight]);
  const anyLit = useMemo(() => l.nodes.some((n) => order.has(n.id)), [l, order]);
  const lit = useMemo(() => (anyLit ? litEdges(l, order) : new Set<string>()), [l, order, anyLit]);
  return (
    <>
      <svg className="edges" style={{ left: l.box.x, top: l.box.y }} width={l.box.w} height={l.box.h} viewBox={`${l.box.x} ${l.box.y} ${l.box.w} ${l.box.h}`}>
        <defs>
          <marker id="arr" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M1.5 1.5 8.5 5 1.5 8.5" fill="none" stroke="context-stroke" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </marker>
        </defs>
        {l.edges.map((e) => {
          const on = lit.has(e.id);
          const near = hover !== null && (e.from === hover || e.to === hover);
          const d = pathOf(e.points);
          return (
            <g key={e.id} className={`edge${on ? " is-lit" : ""}${near ? " is-near" : ""}${anyLit && !on ? " is-dim" : ""}${e.back ? " is-back" : ""}`}>
              <path d={d} className="edge-line" markerEnd="url(#arr)" />
              {on && <path d={d} className="edge-flow" />}
            </g>
          );
        })}
      </svg>
      {l.edges.map((e) => {
        if (!e.label) return null;
        const p = e.wrap ? { x: e.points[0].x, y: e.points[0].y + 13 } : e.points[Math.min(1, e.points.length - 1)];
        return (
          <span key={e.id} className={`edge-label ${e.label === "Yes" ? "yes" : "no"}`} style={{ left: p.x, top: p.y }}>
            {e.label}
          </span>
        );
      })}
      {l.nodes.map((n, i) =>
        n.port ? (
          <span key={n.id} className={`port ${n.port}`} style={{ left: n.x, top: n.y, width: n.w, height: n.h }} title={n.port === "in" ? "Enters here" : "Continues in the caller"} />
        ) : (
          <div key={n.id} className={props.portal === n.id ? "portal" : undefined}>
            <Card
              id={n.id}
              x={n.x}
              y={n.y}
              w={n.w}
              h={n.h}
              index={i}
              selected={selected === n.id}
              hovered={hover === n.id}
              lit={order.has(n.id) ? order.get(n.id)! : null}
              dim={anyLit && !order.has(n.id)}
            />
          </div>
        ),
      )}
    </>
  );
});

export function Canvas() {
  const scope = useStore((s) => s.scope);
  const selected = useStore((s) => s.selected);
  const hover = useStore((s) => s.hover);
  const highlight = useStore((s) => s.highlight);
  const focusTick = useStore((s) => s.focusTick);
  const panelOn = useStore((s) => s.panel);
  const touched = useStore((s) => s.touched);

  const wrap = useRef<HTMLDivElement>(null);
  const curEl = useRef<HTMLDivElement>(null);
  const prevEl = useRef<HTMLDivElement>(null);
  const panelEl = useRef<HTMLDivElement>(null);
  const [vp, setVp] = useState<Size>({ w: 0, h: 0 });
  const vpRef = useRef(vp);
  vpRef.current = vp;
  // Level 0: whichever column count shows the stage cards largest
  const cols = useMemo(() => {
    if (!vp.w || !vp.h) return 4;
    return [4, 3, 2].reduce((best, c) => (camFor(layoutOf(ROOT, c), vp).k > camFor(layoutOf(ROOT, best), vp).k + 0.02 ? c : best), 4);
  }, [vp]);

  const [layers, setLayers] = useState<{ cur: string; prev: string | null; mode: "in" | "out" | "fade" | null }>({ cur: scope, prev: null, mode: null });
  const cam = useRef<Cam>({ x: 0, y: 0, k: 1 });
  const baseK = useRef(1);
  const raf = useRef(0);
  const pending = useRef<null | { end: Cam }>(null);
  const quietUntil = useRef(0);
  const zoomHint = useRef(0);

  /** The panel parks in the top-right corner when its node is not in the chart; keep the chart clear of it. */
  const usable = useCallback((l: Layout): Size => {
    const { w, h } = vpRef.current;
    const sel = getState().selected;
    const parked = sel !== null && getState().panel && !l.byId[sel] && w >= 900;
    return { w: parked ? w - PANEL_W - 20 : w, h };
  }, []);

  const layout = useCallback((s: string) => layoutOf(s, cols, vp), [cols, vp]);
  const curLayout = layout(layers.cur);
  const prevLayout = layers.prev ? layout(layers.prev) : null;

  const placePanel = useCallback(() => {
    const el = panelEl.current;
    const { selected: sel } = getState();
    if (!el || !sel) return;
    const r = layoutOf(layers.cur, cols, vpRef.current).byId[sel];
    const { w, h } = vpRef.current;
    const ph = el.offsetHeight, pw = el.offsetWidth;
    if (!r || w < 720) {
      el.dataset.mode = w < 720 ? "sheet" : "corner";
      el.style.transform = "";
      return;
    }
    el.dataset.mode = "float";
    const c = cam.current;
    const left = r.x * c.k + c.x, top = r.y * c.k + c.y, right = left + r.w * c.k;
    let x = right + 16;
    if (x + pw > w - 10) x = left - pw - 16;
    if (x < 10) x = clamp(right + 16, 10, w - pw - 10);
    const y = clamp(top - 6, 10, Math.max(10, h - ph - 10));
    el.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
  }, [layers.cur, cols]);

  const apply = useCallback(() => {
    const c = cam.current;
    if (curEl.current) curEl.current.style.transform = `translate(${c.x}px, ${c.y}px) scale(${c.k})`;
    placePanel();
  }, [placePanel]);

  const stop = () => {
    cancelAnimationFrame(raf.current);
    if (pending.current) {
      cam.current = pending.current.end;
      pending.current = null;
    }
  };

  const glide = useCallback(
    (to: Cam, ms = 420) => {
      stop();
      const from = { ...cam.current };
      const t0 = performance.now();
      pending.current = { end: to };
      const dur = Math.min(ms, transitionMs());
      const step = (now: number) => {
        const e = ease(clamp((now - t0) / dur, 0, 1));
        const k = from.k * Math.pow(to.k / from.k, e);
        cam.current = { k, x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e };
        apply();
        if (e < 1) raf.current = requestAnimationFrame(step);
        else pending.current = null;
      };
      raf.current = requestAnimationFrame(step);
    },
    [apply],
  );

  // viewport size
  useLayoutEffect(() => {
    const el = wrap.current!;
    const ro = new ResizeObserver(() => setVp({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setVp({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // refit when the viewport changes
  const sized = useRef(false);
  useLayoutEffect(() => {
    if (!vp.w || !vp.h) return;
    const target = camFor(layoutOf(layers.cur, cols, vp), vp);
    baseK.current = target.k;
    if (!sized.current) {
      sized.current = true;
      cam.current = target;
      apply();
    } else if (!layers.prev) glide(target, 300);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vp.w, vp.h, cols]);

  // a new scope in the store starts a level transition
  useLayoutEffect(() => {
    if (scope === layers.cur) return;
    stop();
    const from = layers.cur;
    const mode = lineage(scope).includes(from) ? "in" : lineage(from).includes(scope) ? "out" : "fade";
    setLayers({ cur: scope, prev: from, mode });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope]);

  // run the transition once both layers are in the DOM
  useLayoutEffect(() => {
    if (!layers.prev || !prevLayout || !vp.w) return;
    const size = usable(curLayout);
    const oldCam = { ...cam.current };
    const parent = layers.mode === "in" ? prevLayout : curLayout;
    const child = layers.mode === "in" ? curLayout : prevLayout;
    const rel = layers.mode === "fade" ? null : nest(parent, child);
    const newEl = curEl.current!, oldEl = prevEl.current!;
    const css = (c: Cam) => `translate(${c.x}px, ${c.y}px) scale(${c.k})`;
    const toChild = (p: Cam): Cam => ({ k: p.k * rel!.m, x: p.x + p.k * rel!.tx, y: p.y + p.k * rel!.ty });
    const toParent = (c: Cam): Cam => {
      const k = c.k / rel!.m;
      return { k, x: c.x - k * rel!.tx, y: c.y - k * rel!.ty };
    };

    let endCam: Cam;
    let frame: (e: number) => void;
    if (!rel) {
      endCam = camFor(curLayout, size);
      frame = (e) => {
        cam.current = endCam;
        newEl.style.transform = css(endCam);
        newEl.style.opacity = String(e);
        oldEl.style.transform = css(oldCam);
        oldEl.style.opacity = String(1 - e);
      };
    } else {
      // Both charts move as one rigid picture: the child chart is pinned inside its node.
      const parentEnd = layers.mode === "out" ? camFor(parent, size, rel.rect) : null;
      const c0 = layers.mode === "in" ? toChild(oldCam) : oldCam;
      const c1 = layers.mode === "in" ? camFor(child, size) : toChild(parentEnd!);
      endCam = layers.mode === "in" ? c1 : parentEnd!;
      const ax = child.box.x + child.box.w / 2, ay = child.box.y + child.box.h / 2;
      const s0 = { x: c0.x + c0.k * ax, y: c0.y + c0.k * ay };
      const s1 = { x: c1.x + c1.k * ax, y: c1.y + c1.k * ay };
      frame = (e) => {
        const k = c0.k * Math.pow(c1.k / c0.k, e);
        const c: Cam = { k, x: s0.x + (s1.x - s0.x) * e - k * ax, y: s0.y + (s1.y - s0.y) * e - k * ay };
        const p = toParent(c);
        const [childEl, parentEl] = layers.mode === "in" ? [newEl, oldEl] : [oldEl, newEl];
        childEl.style.transform = css(c);
        parentEl.style.transform = css(p);
        if (layers.mode === "in") {
          childEl.style.opacity = String(ramp(e, 0.28, 0.8));
          parentEl.style.opacity = String(1 - ramp(e, 0.3, 0.85));
        } else {
          childEl.style.opacity = String(1 - ramp(e, 0.15, 0.6));
          parentEl.style.opacity = String(ramp(e, 0.12, 0.6));
        }
        cam.current = layers.mode === "in" ? c : p;
      };
    }

    baseK.current = camFor(curLayout, size).k;
    pending.current = { end: endCam };
    const dur = transitionMs();
    const t0 = performance.now();
    frame(0);
    const step = (now: number) => {
      const t = clamp((now - t0) / dur, 0, 1);
      frame(ease(t));
      if (t < 1) raf.current = requestAnimationFrame(step);
      else {
        pending.current = null;
        cam.current = endCam;
        newEl.style.opacity = "";
        quietUntil.current = performance.now() + 380;
        setLayers((s) => ({ cur: s.cur, prev: null, mode: null }));
      }
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layers.prev, layers.cur]);

  useLayoutEffect(() => {
    if (!layers.prev) apply();
  }, [layers.prev, apply]);

  // keep the selected node and its panel in view
  useEffect(() => {
    if (!selected || layers.prev) return;
    const r = curLayout.byId[selected];
    if (!r) return;
    const id = requestAnimationFrame(() => {
      const c = cam.current, { w, h } = vpRef.current;
      const room = w >= 720 && getState().panel ? PANEL_W + 28 : 0;
      const left = r.x * c.k + c.x, top = r.y * c.k + c.y;
      const right = left + r.w * c.k, bottom = top + r.h * c.k;
      let dx = 0, dy = 0;
      const fitsRight = right + room <= w - 8, fitsLeft = left - room >= 8;
      if (!fitsRight && !fitsLeft) dx = w - 16 - room - right;
      if (left + dx < 16) dx = 16 - left;
      const sheet = w < 720 ? Math.min(h * 0.5, 360) : 0;
      if (top < 20) dy = 20 - top;
      else if (bottom > h - 20 - sheet) dy = h - 20 - sheet - bottom;
      if (dx || dy) glide({ k: c.k, x: c.x + dx, y: c.y + dy }, 380);
      else placePanel();
    });
    return () => cancelAnimationFrame(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, focusTick, layers.prev, layers.cur]);

  // ---- direct manipulation -------------------------------------------------
  const zoomAt = useCallback(
    (factor: number, px: number, py: number) => {
      const c = cam.current;
      const lo = baseK.current * (getState().scope === ROOT ? 1 : 0.5);
      const k = clamp(c.k * factor, lo, baseK.current * 3);
      const f = k / c.k;
      cam.current = { k, x: px - (px - c.x) * f, y: py - (py - c.y) * f };
      apply();
      return k;
    },
    [apply],
  );

  useEffect(() => {
    const el = wrap.current!;
    const onWheel = (ev: WheelEvent) => {
      if ((ev.target as HTMLElement).closest(".node-panel")) return;
      const out = ev.deltaY > 0;
      const state = getState();
      // the page scrolls once the chart is fully zoomed out, or when the demo is not at the top
      if (window.scrollY > 4) return;
      if (state.scope === ROOT && out && cam.current.k <= baseK.current * 1.001) return;
      ev.preventDefault();
      if (layers.prev || performance.now() < quietUntil.current) return;
      stop();
      const rect = el.getBoundingClientRect();
      const px = ev.clientX - rect.left, py = ev.clientY - rect.top;
      const unit = ev.deltaMode === 1 ? 16 : 1;
      const k = zoomAt(Math.exp(-ev.deltaY * unit * (ev.ctrlKey ? 0.012 : 0.0024)), px, py);
      if (!state.touched) set({ touched: true });
      if (!out && k > baseK.current * 1.7) {
        const hit = (document.elementFromPoint(ev.clientX, ev.clientY) as HTMLElement | null)?.closest<HTMLElement>("[data-id]");
        const id = hit?.dataset.id;
        if (id && canEnter(id)) openNode(id);
        else if (performance.now() - zoomHint.current > 2500) {
          zoomHint.current = performance.now();
          el.classList.add("nudge");
          setTimeout(() => el.classList.remove("nudge"), 900);
        }
      } else if (out && state.scope !== ROOT && k < baseK.current * 0.64) goUp();
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomAt, layers.prev]);

  const drag = useRef<null | { id: number; x: number; y: number; moved: boolean; target: HTMLElement }>(null);
  const touches = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<null | { d: number }>(null);

  const onPointerDown = (ev: React.PointerEvent) => {
    if ((ev.target as HTMLElement).closest(".node-panel, .canvas-ui")) return;
    touches.current.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (touches.current.size === 2) {
      const [a, b] = [...touches.current.values()];
      pinch.current = { d: Math.hypot(a.x - b.x, a.y - b.y) };
      drag.current = null;
      return;
    }
    stop();
    drag.current = { id: ev.pointerId, x: ev.clientX, y: ev.clientY, moved: false, target: ev.target as HTMLElement };
  };
  const onPointerMove = (ev: React.PointerEvent) => {
    if (touches.current.has(ev.pointerId)) touches.current.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (pinch.current && touches.current.size === 2 && !layers.prev) {
      const [a, b] = [...touches.current.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      const rect = wrap.current!.getBoundingClientRect();
      const cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2;
      const k = zoomAt(d / pinch.current.d, cx - rect.left, cy - rect.top);
      pinch.current.d = d;
      if (performance.now() < quietUntil.current) return;
      if (k > baseK.current * 1.7) {
        const id = (document.elementFromPoint(cx, cy) as HTMLElement | null)?.closest<HTMLElement>("[data-id]")?.dataset.id;
        if (id && canEnter(id)) openNode(id);
      } else if (k < baseK.current * 0.64 && getState().scope !== ROOT) goUp();
      return;
    }
    const d = drag.current;
    if (!d || d.id !== ev.pointerId) return;
    const dx = ev.clientX - d.x, dy = ev.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 5) return;
    if (!d.moved) {
      d.moved = true;
      wrap.current!.setPointerCapture(ev.pointerId);
      wrap.current!.classList.add("is-panning");
    }
    cam.current = { ...cam.current, x: cam.current.x + dx, y: cam.current.y + dy };
    d.x = ev.clientX;
    d.y = ev.clientY;
    apply();
  };
  const onPointerUp = (ev: React.PointerEvent) => {
    touches.current.delete(ev.pointerId);
    if (touches.current.size < 2) pinch.current = null;
    const d = drag.current;
    drag.current = null;
    wrap.current!.classList.remove("is-panning");
    if (!d || d.moved || layers.prev) return;
    const open = d.target.closest<HTMLElement>("[data-open]");
    if (open) return openNode(open.dataset.open!);
    const card = d.target.closest<HTMLElement>("[data-id]");
    if (!card && !getState().selected) return;
    clearThread("panel");
    select(card && card.dataset.id !== getState().selected ? card.dataset.id! : null);
  };
  const onDoubleClick = (ev: React.MouseEvent) => {
    const id = (ev.target as HTMLElement).closest<HTMLElement>("[data-id]")?.dataset.id;
    if (id && canEnter(id)) openNode(id);
  };
  const onOver = (ev: React.PointerEvent) => {
    if (ev.pointerType === "touch") return;
    const id = (ev.target as HTMLElement).closest<HTMLElement>("[data-id]")?.dataset.id ?? null;
    if (id !== getState().hover) set({ hover: id });
  };
  const onKeyDown = (ev: React.KeyboardEvent) => {
    const id = (ev.target as HTMLElement).dataset?.id;
    if (id && ev.key === "Enter") {
      if (ev.shiftKey || !canEnter(id)) select(id);
      else openNode(id);
    } else if (id && ev.key === " ") {
      ev.preventDefault();
      select(id);
    }
  };

  // Escape closes the panel, then walks back up a level
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key !== "Escape") return;
      if (getState().selected && getState().panel) (clearThread("panel"), select(null));
      else goUp();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const center = () => ({ x: vpRef.current.w / 2, y: vpRef.current.h / 2 });
  const zoomBy = (f: number) => {
    const c = cam.current, p = center();
    const k = clamp(c.k * f, baseK.current * (scope === ROOT ? 1 : 0.66), baseK.current * 2.6);
    const r = k / c.k;
    glide({ k, x: p.x - (p.x - c.x) * r, y: p.y - (p.y - c.y) * r }, 220);
  };
  const up = parentScope(scope);
  const portal = layers.mode === "in" && layers.prev ? shownIn(layers.prev, layers.cur) : null;
  const panelNode = selected && panelOn && !layers.prev ? selected : null;

  return (
    <div
      ref={wrap}
      className={`canvas${layers.prev ? " is-moving" : ""}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onPointerOver={onOver}
      onPointerLeave={() => getState().hover && set({ hover: null })}
      onDoubleClick={onDoubleClick}
      onKeyDown={onKeyDown}
    >
      {prevLayout && (
        <div ref={prevEl} className="layer is-leaving" key={`${layers.prev}:old`}>
          <ScopeLayer layout={prevLayout} selected={null} hover={null} highlight={highlight} portal={portal} />
        </div>
      )}
      <div ref={curEl} className={`layer${layers.mode ? ` enter-${layers.mode}` : ""}`} key={layers.cur} style={layers.prev ? { opacity: 0 } : undefined}>
        <ScopeLayer layout={curLayout} selected={selected} hover={hover} highlight={highlight} portal={null} />
      </div>

      <div ref={panelEl} className={`panel-anchor${panelNode ? " is-open" : ""}`} data-mode="float">
        {panelNode && <NodePanel key={panelNode} id={panelNode} onResize={placePanel} />}
      </div>

      <div className="canvas-ui bottom-left">
        <div className="zoom">
          <button onClick={() => zoomBy(1 / 1.3)} aria-label="Zoom out">−</button>
          <button onClick={() => glide(camFor(curLayout, usable(curLayout)), 320)} aria-label="Fit to view" className="fit">Fit</button>
          <button onClick={() => zoomBy(1.3)} aria-label="Zoom in">+</button>
        </div>
        {up && (
          <button className="up" onClick={goUp}>
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden><path d="M2.5 7 6 3.5 9.5 7M6 3.5V10" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
            Up to {node(up).title}
          </button>
        )}
      </div>
      {highlight.length > 0 && (
        <button className="canvas-ui path-chip" onClick={() => setHighlight([])}>
          <span className="flow-dot" />
          Execution path highlighted
          <span className="x">Clear</span>
        </button>
      )}
      {!touched && (
        <div className="canvas-ui hint">
          <b>Click</b> a step to inspect it · <b>double-click</b> or <b>scroll</b> to zoom in
        </div>
      )}
      <div className="canvas-ui nudge-msg">Point at a step with “Zoom in” to go deeper</div>
    </div>
  );
}
