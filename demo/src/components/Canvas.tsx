import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { clearThread } from "../lib/ask";
import { ROOT, canEnter, enterTarget, leafCount, node, parentScope, scopeTrail, shownIn, type GNode } from "../lib/graph";
import { IN, OUT, labelLines, layoutOf, pathOf, type LEdge, type Layout } from "../lib/layout";
import { arrived, getState, goUp, highlightOrder, motion, openNode, select, set, setHighlight, useStore } from "../store";
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
interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}
/** How a child chart sits inside the step that stands for it: child world -> parent world. */
interface Nest {
  rect: Rect;
  m: number;
  tx: number;
  ty: number;
}

const PAD = 48;
const PANEL_W = 352;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const ramp = (t: number, a: number, b: number) => clamp((t - a) / (b - a), 0, 1);
const css = (c: Cam) => `translate(${c.x}px, ${c.y}px) scale(${c.k})`;

/*
 * Zoom is one continuous quantity. For a chart, z = (its scale on screen) / (its scale
 * when fitted to the view). A chart fades in as z goes 0.2 -> 0.5, and the chart around
 * it fades out as z goes 0.32 -> 0.62. Which chart is "current" (takes clicks, owns the
 * breadcrumb) flips near z = 0.44, with a little hysteresis. Nothing jumps at the flip,
 * because both charts are drawn as one rigid picture the whole time.
 */
const SHOW = [0.2, 0.5] as const;
const HIDE = [0.32, 0.62] as const;
const FLIP_IN = 0.46;
const FLIP_OUT = 0.42;

/** Camera that fits a chart in the view, optionally keeping one step in sight. */
function camFor(l: Layout, vp: Size, focus?: Rect): Cam {
  const fit = Math.min((vp.w - PAD * 2) / l.box.w, (vp.h - PAD * 2) / l.box.h);
  const k = clamp(fit, 0.34, 1.1);
  const fitsW = l.box.w * k <= vp.w - PAD * 2 + 1;
  const fitsH = l.box.h * k <= vp.h - PAD * 2 + 1;
  const start = l.byId[IN];
  let x = fitsW ? vp.w / 2 - k * (l.box.x + l.box.w / 2) : PAD - k * (start ? start.x : l.box.x);
  let y = fitsH ? vp.h / 2 - k * (l.box.y + l.box.h / 2) : vp.h / 2 - k * (start ? start.y + start.h / 2 : l.box.y);
  if (focus) {
    if (!fitsW) x = clamp(vp.w / 2 - k * (focus.x + focus.w / 2), vp.w - PAD - k * (l.box.x + l.box.w), PAD - k * l.box.x);
    if (!fitsH) y = clamp(vp.h / 2 - k * (focus.y + focus.h / 2), vp.h - PAD - k * (l.box.y + l.box.h), PAD - k * l.box.y);
  }
  return { x, y, k };
}

function nestOf(parent: Layout, child: Layout, nodeId: string | null): Nest | null {
  const r = nodeId ? parent.byId[nodeId] : null;
  if (!r) return null;
  const m = Math.min(r.w / child.box.w, r.h / child.box.h) * 0.92;
  return { rect: r, m, tx: r.x + r.w / 2 - m * (child.box.x + child.box.w / 2), ty: r.y + r.h / 2 - m * (child.box.y + child.box.h / 2) };
}
const toChild = (p: Cam, n: Nest): Cam => ({ k: p.k * n.m, x: p.x + p.k * n.tx, y: p.y + p.k * n.ty });
const toParent = (c: Cam, n: Nest): Cam => {
  const k = c.k / n.m;
  return { k, x: c.x - k * n.tx, y: c.y - k * n.ty };
};

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
  if (n.kind === "group") return "Steps";
  if (n.type === "call") return "Call";
  return TAGS[n.kind] ?? (n.type === "decision" ? "If" : "Action");
}
export function toneOf(n: GNode): string {
  if (n.type === "call") return "call";
  if (n.type === "decision") return "decision";
  if (n.loop) return "loop";
  if (n.kind === "group") return "group";
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
  for (const e of l.edges) if (!e.skip) (out.get(e.from) ?? out.set(e.from, []).get(e.from)!).push(e);
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

/** A miniature of the chart inside a step: its shape (sequence, branches, loops) before you zoom in. */
const Mini = memo(function Mini({ id }: { id: string }) {
  const target = enterTarget(id);
  if (!target) return null;
  const l = layoutOf(target);
  return (
    <svg className="mini" viewBox={`${l.box.x - 8} ${l.box.y - 8} ${l.box.w + 16} ${l.box.h + 16}`} preserveAspectRatio="xMidYMid meet" aria-hidden>
      {l.edges.map((e) => (
        <path key={e.id} d={pathOf(e.points)} className={`mini-edge${e.back ? " back" : ""}${e.skip ? " skip" : ""}`} />
      ))}
      {l.nodes.map((n) =>
        n.port ? (
          <circle key={n.id} cx={n.x + n.w / 2} cy={n.y + n.h / 2} r={n.w / 2} className={`mini-port ${n.port}`} />
        ) : (
          <rect key={n.id} x={n.x} y={n.y} width={n.w} height={n.h} rx={22} className={`mini-node tone-${toneOf(node(n.id))}`} />
        ),
      )}
    </svg>
  );
});

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
    "--lines": labelLines(n.id),
  } as React.CSSProperties;
  const enterable = canEnter(n.id);
  const named = n.kind === "group";
  const cls = [
    "card",
    `tone-${toneOf(n)}`,
    enterable && "is-deep",
    props.selected && "is-selected",
    props.hovered && "is-hover",
    props.lit !== null && "is-lit",
    props.dim && "is-dim",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={cls} style={style} data-id={n.id} tabIndex={0} role="button" aria-label={n.label}>
      <div className="card-tag">
        <span className="glyph" />
        <span>{tagOf(n)}</span>
        {n.loop && <span className="mark">repeats</span>}
        {n.guard && <span className="mark" title={`runs only if ${n.guard}`}>conditional</span>}
        <span className="card-lines">{linesOf(n)}</span>
      </div>
      <div className={named ? "card-title named" : "card-title"}>{n.title}</div>
      <div className="card-label">{n.label}</div>
      {enterable && (
        <button className="card-open" data-open={n.id} tabIndex={-1}>
          <Mini id={n.id} />
          <span className="card-count">{leafCount(n.id)}</span>
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
}) {
  const { layout: l, selected, hover, highlight } = props;
  const order = useMemo(() => highlightOrder(highlight), [highlight]);
  const anyLit = useMemo(() => l.nodes.some((n) => order.has(n.id)), [l, order]);
  const lit = useMemo(() => (anyLit ? litEdges(l, order) : new Set<string>()), [l, order, anyLit]);
  return (
    <>
      <svg className="edges" style={{ left: l.box.x, top: l.box.y }} width={l.box.w} height={l.box.h} viewBox={`${l.box.x} ${l.box.y} ${l.box.w} ${l.box.h}`}>
        {l.edges.map((e) => {
          const on = lit.has(e.id);
          const near = hover !== null && (e.from === hover || e.to === hover);
          const d = pathOf(e.points);
          const cls = `edge${on ? " is-lit" : ""}${near ? " is-near" : ""}${anyLit && !on ? " is-dim" : ""}${e.back ? " is-back" : ""}${e.skip ? " is-skip" : ""}`;
          return (
            <g key={e.id} className={cls}>
              <path d={d} className="edge-line" markerEnd="url(#arr)" />
              {on && <path d={d} className="edge-flow" />}
            </g>
          );
        })}
      </svg>
      {l.edges.map((e) => {
        if (!e.label) return null;
        const p = e.points[Math.floor(e.points.length / 2)];
        return (
          <span key={e.id} className={`edge-label ${e.label === "Yes" ? "yes" : e.label === "No" ? "no" : "skip"}`} style={{ left: p.x, top: p.y }}>
            {e.label}
          </span>
        );
      })}
      {l.nodes.map((n, i) =>
        n.port ? (
          <span key={n.id} className={`port ${n.port}`} style={{ left: n.x, top: n.y, width: n.w, height: n.h }} title={n.port === "in" ? "Enters here" : "Continues in the level above"} />
        ) : (
          <Card
            key={n.id}
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
        ),
      )}
    </>
  );
});

interface View {
  cur: string;
  /** the step being zoomed into, and the chart that is appearing inside it */
  portal: { node: string; scope: string } | null;
}

export function Canvas() {
  const scope = useStore((s) => s.scope);
  const selected = useStore((s) => s.selected);
  const hover = useStore((s) => s.hover);
  const highlight = useStore((s) => s.highlight);
  const focusTick = useStore((s) => s.focusTick);
  const touched = useStore((s) => s.touched);
  const panelOn = useStore((s) => s.panel);

  const wrap = useRef<HTMLDivElement>(null);
  const panelEl = useRef<HTMLDivElement>(null);
  const els = useRef(new Map<string, HTMLDivElement>());
  const [vp, setVp] = useState<Size>({ w: 0, h: 0 });
  const vpRef = useRef(vp);
  vpRef.current = vp;

  const [view, setViewState] = useState<View>({ cur: scope, portal: null });
  const viewRef = useRef(view);
  const [busy, setBusy] = useState(false);
  const cam = useRef<Cam>({ x: 0, y: 0, k: 1 });
  const raf = useRef(0);
  const glideDone = useRef<null | (() => void)>(null);
  const navToken = useRef(0);
  const settleTimer = useRef(0);
  const revealed = useRef<HTMLElement[]>([]);

  const setView = (v: View) => {
    viewRef.current = v;
    setViewState(v);
  };

  /** The panel parks in the top-right corner when its node is not in the chart; keep the chart clear of it. */
  const usable = useCallback((l: Layout): Size => {
    const { w, h } = vpRef.current;
    const st = getState();
    const parked = st.selected !== null && st.panel && !l.byId[st.selected] && w >= 900;
    return { w: parked ? w - PANEL_W - 20 : w, h };
  }, []);
  const fitCam = useCallback((s: string, focus?: Rect) => camFor(layoutOf(s), usable(layoutOf(s)), focus), [usable]);
  const fitK = (s: string) => camFor(layoutOf(s), vpRef.current).k;

  const placePanel = useCallback(() => {
    const el = panelEl.current;
    const sel = getState().selected;
    if (!el || !sel) return;
    const r = layoutOf(viewRef.current.cur).byId[sel];
    const { w, h } = vpRef.current;
    if (!r || w < 720) {
      el.dataset.mode = w < 720 ? "sheet" : "corner";
      el.style.transform = "";
      return;
    }
    el.dataset.mode = "float";
    const c = cam.current, ph = el.offsetHeight, pw = el.offsetWidth;
    const left = r.x * c.k + c.x, top = r.y * c.k + c.y, right = left + r.w * c.k;
    let x = right + 16;
    if (x + pw > w - 10) x = left - pw - 16;
    if (x < 10) x = clamp(right + 16, 10, w - pw - 10);
    const y = clamp(top - 6, 10, Math.max(10, h - ph - 10));
    el.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
  }, []);

  /** Draw the current camera: place the three charts as one picture, fade them by zoom, flip when due. */
  const apply = useCallback(() => {
    for (let guard = 0; guard < 4; guard++) {
      const v = viewRef.current, c = cam.current;
      const L = layoutOf(v.cur);
      const parent = parentScope(v.cur);
      const up = parent ? nestOf(layoutOf(parent), L, shownIn(parent, v.cur)) : null;
      const down = v.portal ? nestOf(L, layoutOf(v.portal.scope), v.portal.node) : null;
      const z = c.k / fitK(v.cur);
      const cc = down ? toChild(c, down) : null;
      const zc = cc && v.portal ? cc.k / fitK(v.portal.scope) : 0;

      if (parent && up && z < FLIP_OUT) {
        // zoomed out far enough: the surrounding chart becomes the current one
        const st = getState();
        cam.current = toParent(c, up);
        setView({ cur: parent, portal: { node: shownIn(parent, v.cur)!, scope: v.cur } });
        const drop = st.selected && !layoutOf(parent).byId[st.selected] && !st.driving;
        if (st.scope !== parent) set({ scope: parent, ...(drop ? { selected: null } : {}) });
        continue;
      }
      if (v.portal && cc && zc > FLIP_IN) {
        // zoomed in far enough: the chart inside the step becomes the current one
        cam.current = cc;
        setView({ cur: v.portal.scope, portal: null });
        if (getState().scope !== v.portal.scope) set({ scope: v.portal.scope, touched: true, ...(getState().driving ? {} : { selected: null }) });
        continue;
      }

      const paint = (id: string, camera: Cam, opacity: number, live: boolean) => {
        const el = els.current.get(id);
        if (!el) return;
        el.style.transform = css(camera);
        el.style.opacity = String(opacity);
        el.style.pointerEvents = live && opacity > 0.5 ? "auto" : "none";
        el.style.visibility = opacity <= 0.001 ? "hidden" : "visible";
        // level of detail: far away, a card shows its title large and nothing else
        el.style.setProperty("--lod", String(clamp(0.78 / camera.k, 1, 2.3)));
        el.classList.toggle("is-far", camera.k < 0.62);
      };
      const curOpacity = (parent && up ? ramp(z, SHOW[0], SHOW[1]) : 1) * (cc ? 1 - ramp(zc, HIDE[0], HIDE[1]) : 1);
      paint(v.cur, c, curOpacity, true);
      if (parent && up) paint(parent, toParent(c, up), 1 - ramp(z, HIDE[0], HIDE[1]), false);
      if (v.portal && cc) paint(v.portal.scope, cc, ramp(zc, SHOW[0], SHOW[1]), false);

      // the step being entered empties out as its chart appears inside it
      for (const el of revealed.current) el.style.removeProperty("--reveal");
      revealed.current = [];
      const mark = (layer: string, id: string | null, amount: number) => {
        const card = id ? els.current.get(layer)?.querySelector<HTMLElement>(`[data-id="${CSS.escape(id)}"]`) : null;
        if (card && amount > 0) (card.style.setProperty("--reveal", String(amount)), revealed.current.push(card));
      };
      if (v.portal) mark(v.cur, v.portal.node, ramp(zc, 0.1, 0.3));
      if (parent) mark(parent, shownIn(parent, v.cur), ramp(z, 0.1, 0.3));
      placePanel();
      return;
    }
  }, [placePanel]);

  const stopGlide = () => {
    cancelAnimationFrame(raf.current);
    glideDone.current?.();
    glideDone.current = null;
  };

  /** Camera of the current chart, expressed in an adjacent chart's coordinates (or back). */
  const convert = (c: Cam, from: string, to: string): Cam => {
    if (from === to) return c;
    if (parentScope(from) === to) {
      const n = nestOf(layoutOf(to), layoutOf(from), shownIn(to, from));
      return n ? toParent(c, n) : c;
    }
    const n = nestOf(layoutOf(from), layoutOf(to), shownIn(from, to));
    return n ? toChild(c, n) : c;
  };

  /** Animate to a camera given in `target`'s coordinates. `target` is the current chart or next to it. */
  const glideTo = useCallback(
    (target: string, to: Cam, ms: number): Promise<void> => {
      stopGlide();
      const from = convert(cam.current, viewRef.current.cur, target);
      const box = layoutOf(target).box;
      const ax = box.x + box.w / 2, ay = box.y + box.h / 2;
      const s0 = { x: from.x + from.k * ax, y: from.y + from.k * ay };
      const s1 = { x: to.x + to.k * ax, y: to.y + to.k * ay };
      const dur = Math.max(1, ms * motion());
      const t0 = performance.now();
      return new Promise((resolve) => {
        glideDone.current = resolve;
        const step = (now: number) => {
          const t = clamp((now - t0) / dur, 0, 1), e = ease(t);
          const k = from.k * Math.pow(to.k / from.k, e);
          const c: Cam = { k, x: s0.x + (s1.x - s0.x) * e - k * ax, y: s0.y + (s1.y - s0.y) * e - k * ay };
          cam.current = convert(c, target, viewRef.current.cur);
          apply();
          if (t < 1) raf.current = requestAnimationFrame(step);
          else {
            if (viewRef.current.cur !== target) {
              cam.current = to;
              setView({ cur: target, portal: null });
              if (getState().scope !== target) set({ scope: target });
              apply();
            }
            glideDone.current = null;
            resolve();
          }
        };
        raf.current = requestAnimationFrame(step);
      });
    },
    [apply],
  );

  /** Travel to any scope, one level at a time, as one continuous move. */
  const travel = useCallback(
    async (to: string) => {
      const token = ++navToken.current;
      const a = scopeTrail(viewRef.current.cur), b = scopeTrail(to);
      let i = 0;
      while (i < a.length && i < b.length && a[i] === b[i]) i++;
      const hops = [...a.slice(i - 1, -1).reverse(), ...b.slice(i)];
      const ms = clamp(1150 / Math.max(1, hops.length), 420, 760);
      setBusy(true);
      for (const hop of hops) {
        const cur = viewRef.current.cur;
        if (parentScope(cur) === hop) {
          await glideTo(hop, fitCam(hop, layoutOf(hop).byId[shownIn(hop, cur) ?? ""]), ms * 0.85);
        } else {
          setView({ cur, portal: { node: shownIn(cur, hop)!, scope: hop } });
          await new Promise((r) => requestAnimationFrame(r));
          await glideTo(hop, fitCam(hop), ms);
        }
        if (token !== navToken.current) return;
      }
      setBusy(false);
      arrived();
    },
    [glideTo, fitCam],
  );

  // viewport size
  useLayoutEffect(() => {
    const el = wrap.current!;
    const ro = new ResizeObserver(() => setVp({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setVp({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  const sized = useRef(false);
  useLayoutEffect(() => {
    if (!vp.w || !vp.h) return;
    if (!sized.current) {
      sized.current = true;
      cam.current = fitCam(viewRef.current.cur);
      apply();
    } else if (!busy) void glideTo(viewRef.current.cur, fitCam(viewRef.current.cur), 300);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vp.w, vp.h]);

  // newly mounted layers need their first paint
  useLayoutEffect(apply, [view, apply]);

  // the store asked for another scope (breadcrumb, double-click, an answer driving the diagram)
  useEffect(() => {
    if (scope !== viewRef.current.cur) void travel(scope);
    else arrived();
  }, [scope, travel]);

  // keep the selected node and its panel in view
  useEffect(() => {
    if (!selected || busy) return;
    const r = layoutOf(viewRef.current.cur).byId[selected];
    if (!r) return;
    const id = requestAnimationFrame(() => {
      const c = cam.current, { w, h } = vpRef.current;
      const room = w >= 720 && getState().panel ? PANEL_W + 28 : 0;
      const left = r.x * c.k + c.x, top = r.y * c.k + c.y;
      const right = left + r.w * c.k, bottom = top + r.h * c.k;
      let dx = 0, dy = 0;
      if (right + room > w - 8 && left - room < 8) dx = w - 16 - room - right;
      if (left + dx < 16) dx = 16 - left;
      const sheet = w < 720 ? Math.min(h * 0.5, 360) : 0;
      if (top < 20) dy = 20 - top;
      else if (bottom > h - 20 - sheet) dy = h - 20 - sheet - bottom;
      if (dx || dy) void glideTo(viewRef.current.cur, { k: c.k, x: c.x + dx, y: c.y + dy }, 360);
      else placePanel();
    });
    return () => cancelAnimationFrame(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, focusTick, busy, view.cur]);

  // ---- zooming by hand ---------------------------------------------------------
  const cardAt = (x: number, y: number): string | null => {
    const hit = (document.elementFromPoint(x, y) as HTMLElement | null)?.closest<HTMLElement>("[data-id]");
    return hit && els.current.get(viewRef.current.cur)?.contains(hit) ? hit.dataset.id! : null;
  };

  /** After the wheel stops: never rest half-way between two charts. */
  const settle = useCallback(
    (zoomingIn: boolean) => {
      const v = viewRef.current, c = cam.current;
      const z = c.k / fitK(v.cur);
      const parent = parentScope(v.cur);
      if (v.portal) {
        const n = nestOf(layoutOf(v.cur), layoutOf(v.portal.scope), v.portal.node);
        const zc = n ? toChild(c, n).k / fitK(v.portal.scope) : 0;
        if (zoomingIn && zc >= SHOW[0]) return void glideTo(v.portal.scope, fitCam(v.portal.scope), 420);
        if (zc < 0.08) setView({ cur: v.cur, portal: null });
      }
      if (parent && z < HIDE[1]) {
        if (zoomingIn) void glideTo(v.cur, fitCam(v.cur), 380);
        else void glideTo(parent, fitCam(parent, layoutOf(parent).byId[shownIn(parent, v.cur) ?? ""]), 420);
      }
    },
    [glideTo, fitCam],
  );

  const zoomBy = useCallback(
    (factor: number, px: number, py: number, clientX: number, clientY: number) => {
      navToken.current++;
      stopGlide();
      if (busy) setBusy(false);
      const v = viewRef.current, c = cam.current;
      const zoomingIn = factor > 1;
      if (zoomingIn) {
        // the step under the cursor is the one we are zooming into
        const id = cardAt(clientX, clientY);
        const target = id && canEnter(id) ? enterTarget(id) : null;
        if (id && target && v.portal?.node !== id) {
          const old = v.portal ? nestOf(layoutOf(v.cur), layoutOf(v.portal.scope), v.portal.node) : null;
          const shown = old && v.portal ? toChild(c, old).k / fitK(v.portal.scope) : 0;
          if (shown < SHOW[0]) setView({ cur: v.cur, portal: { node: id, scope: target } });
        }
      }
      const base = fitK(v.cur);
      const lo = v.cur === ROOT ? base * 0.8 : 0;
      const hi = viewRef.current.portal ? Infinity : base * 2.4;
      const k = clamp(c.k * factor, lo, Math.max(hi, c.k));
      const f = k / c.k;
      cam.current = { k, x: px - (px - c.x) * f, y: py - (py - c.y) * f };
      apply();
      if (!getState().touched) set({ touched: true });
      window.clearTimeout(settleTimer.current);
      settleTimer.current = window.setTimeout(() => settle(zoomingIn), 170);
    },
    [apply, settle, busy],
  );

  useEffect(() => {
    const el = wrap.current!;
    const onWheel = (ev: WheelEvent) => {
      if ((ev.target as HTMLElement).closest(".node-panel")) return;
      const out = ev.deltaY > 0;
      // the page scrolls once the top chart is fully zoomed out, or when the demo is not at the top
      if (window.scrollY > 4) return;
      if (viewRef.current.cur === ROOT && out && cam.current.k <= fitK(ROOT) * 1.001) return;
      ev.preventDefault();
      const rect = el.getBoundingClientRect();
      const unit = ev.deltaMode === 1 ? 16 : 1;
      const factor = Math.exp(-ev.deltaY * unit * (ev.ctrlKey ? 0.012 : 0.0026));
      zoomBy(factor, ev.clientX - rect.left, ev.clientY - rect.top, ev.clientX, ev.clientY);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomBy]);

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
    drag.current = { id: ev.pointerId, x: ev.clientX, y: ev.clientY, moved: false, target: ev.target as HTMLElement };
  };
  const onPointerMove = (ev: React.PointerEvent) => {
    if (touches.current.has(ev.pointerId)) touches.current.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (pinch.current && touches.current.size === 2) {
      const [a, b] = [...touches.current.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      const rect = wrap.current!.getBoundingClientRect();
      const cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2;
      if (Math.abs(d - pinch.current.d) > 0.5) zoomBy(d / pinch.current.d, cx - rect.left, cy - rect.top, cx, cy);
      pinch.current.d = d;
      return;
    }
    const d = drag.current;
    if (!d || d.id !== ev.pointerId) return;
    const dx = ev.clientX - d.x, dy = ev.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 5) return;
    if (!d.moved) {
      d.moved = true;
      navToken.current++;
      stopGlide();
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
    if (!d || d.moved) return;
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

  const button = (f: number) => {
    const { w, h } = vpRef.current;
    const rect = wrap.current!.getBoundingClientRect();
    zoomBy(f, w / 2, h / 2, rect.left + w / 2, rect.top + h / 2);
  };
  const up = parentScope(view.cur);
  const panelNode = selected && panelOn && !busy ? selected : null;
  const layers = [up, view.cur, view.portal?.scope].filter((s): s is string => Boolean(s));

  return (
    <div
      ref={wrap}
      className={`canvas${busy ? " is-moving" : ""}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onPointerOver={onOver}
      onPointerLeave={() => getState().hover && set({ hover: null })}
      onDoubleClick={onDoubleClick}
      onKeyDown={onKeyDown}
    >
      {/* one arrowhead for every chart; a marker inside a hidden layer would not paint */}
      <svg width="0" height="0" className="defs" aria-hidden>
        <defs>
          <marker id="arr" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
            <path d="M1 1 9 5 1 9z" fill="context-stroke" />
          </marker>
        </defs>
      </svg>
      {layers.map((s) => (
        <div
          key={s}
          className="layer"
          ref={(el) => {
            if (el) els.current.set(s, el);
            else els.current.delete(s);
          }}
        >
          <ScopeLayer layout={layoutOf(s)} selected={s === view.cur ? selected : null} hover={s === view.cur ? hover : null} highlight={highlight} />
        </div>
      ))}

      <div ref={panelEl} className={`panel-anchor${panelNode ? " is-open" : ""}`} data-mode="float">
        {panelNode && <NodePanel key={panelNode} id={panelNode} onResize={placePanel} />}
      </div>

      <div className="canvas-ui bottom-left">
        <div className="zoom">
          <button onClick={() => button(1 / 1.35)} aria-label="Zoom out">−</button>
          <button onClick={() => void glideTo(viewRef.current.cur, fitCam(viewRef.current.cur), 320)} aria-label="Fit to view" className="fit">Fit</button>
          <button onClick={() => button(1.35)} aria-label="Zoom in">+</button>
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
          <b>Scroll</b> over a step to zoom into it · <b>click</b> to inspect and ask
        </div>
      )}
    </div>
  );
}
