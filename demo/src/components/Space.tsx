import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { clearThread } from "../lib/ask";
import { ROOT, canEnter, enterTarget, node, parentScope, scopeTrail, shownIn } from "../lib/graph";
import { layoutOf } from "../lib/layout";
import { arrived, getState, goTo, goUp, motion, openNode, select, set, useStore } from "../store";
import { ScopeLayer, toneOf } from "./Canvas";
import { NodePanel } from "./NodePanel";

/*
 * The levels as sheets stacked in space. The chart you are in is the middle sheet. Above it
 * hang the charts you came through, each over the step that led down. Below it, the charts
 * inside its steps step down towards the viewer like a staircase, one row per step, so none
 * hides another. Lines join a step to the sheet that expands it.
 *
 * Everything is ordinary DOM under CSS 3D transforms, so the cards are the same cards as in
 * the flat view and their text stays text.
 */

const GAP = 330; // distance between levels
const CHILD_W = 980;
const ROW_GAP = 84; // between two rows of the staircase
const PADDING = 26;
const HOME = { rx: 55, rz: -14 };

interface Sheet {
  scope: string;
  role: "above" | "here" | "below";
  /** chart coordinates -> space: (ox + s*x, oy + s*y, z) */
  ox: number;
  oy: number;
  s: number;
  z: number;
  /** steps away from the current chart, upward */
  far: number;
  /** the step in the sheet above that this sheet expands */
  from: { sheet: string; node: string } | null;
}
interface P3 {
  x: number;
  y: number;
  z: number;
}

function build(scope: string): Sheet[] {
  const trail = scopeTrail(scope);
  const out: Sheet[] = [];
  let prev: Sheet | null = null;
  trail.forEach((t, i) => {
    const box = layoutOf(t).box;
    let cx = 0, cy = 0, from: Sheet["from"] = null;
    if (prev) {
      const step = shownIn(prev.scope, t);
      const r = step ? layoutOf(prev.scope).byId[step] : null;
      if (r && step) {
        cx = prev.ox + prev.s * (r.x + r.w / 2);
        cy = prev.oy + prev.s * (r.y + r.h / 2);
        from = { sheet: prev.scope, node: step };
      }
    }
    const sheet: Sheet = {
      scope: t,
      role: i === trail.length - 1 ? "here" : "above",
      ox: cx - (box.x + box.w / 2),
      oy: cy - (box.y + box.h / 2),
      s: 1,
      z: -i * GAP,
      far: trail.length - 1 - i,
      from,
    };
    out.push(sheet);
    prev = sheet;
  });
  const here = prev as Sheet | null;
  if (!here) return out;
  const L = layoutOf(here.scope);
  let y = here.oy + L.box.y + L.box.h + PADDING + ROW_GAP;
  const steps = L.nodes.filter((n) => !n.port).sort((a, b) => a.x - b.x || a.y - b.y);
  for (const n of steps) {
    const target = enterTarget(n.id);
    if (!target || target === here.scope) continue;
    const box = layoutOf(target).box;
    const s = Math.min(CHILD_W / box.w, 0.66);
    const cx = here.ox + n.x + n.w / 2;
    out.push({
      scope: target,
      role: "below",
      ox: cx - s * (box.x + box.w / 2),
      oy: y + PADDING * s - s * box.y,
      s,
      z: here.z - GAP,
      far: -1,
      from: { sheet: here.scope, node: n.id },
    });
    y += (box.h + PADDING * 2) * s + ROW_GAP;
  }
  return out;
}

const corners = (sh: Sheet, r: { x: number; y: number; w: number; h: number }, pad = 0): P3[] =>
  [
    [r.x - pad, r.y - pad],
    [r.x + r.w + pad, r.y - pad],
    [r.x + r.w + pad, r.y + r.h + pad],
    [r.x - pad, r.y + r.h + pad],
  ].map(([x, y]) => ({ x: sh.ox + sh.s * x, y: sh.oy + sh.s * y, z: sh.z }));

/** A straight line between two points in space, as a thin strip. */
function Beam({ a, b, tone, faint }: { a: P3; b: P3; tone: string; faint: boolean }) {
  const dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
  const len = Math.hypot(dx, dy, dz);
  const yaw = Math.atan2(dy, dx);
  const pitch = -Math.asin(dz / len);
  return (
    <i
      className={`beam tone-${tone}${faint ? " faint" : ""}`}
      style={{ width: len, transform: `translate3d(${a.x}px, ${a.y}px, ${a.z}px) rotateZ(${yaw}rad) rotateY(${pitch}rad)` }}
    />
  );
}

export function Space() {
  const scope = useStore((s) => s.scope);
  const selected = useStore((s) => s.selected);
  const hover = useStore((s) => s.hover);
  const highlight = useStore((s) => s.highlight);
  const panelOn = useStore((s) => s.panel);

  const wrap = useRef<HTMLDivElement>(null);
  const world = useRef<HTMLDivElement>(null);
  const [vp, setVp] = useState({ w: 0, h: 0 });
  const view = useRef({ ...HOME, zoom: 1, px: 0, py: 0 });
  const seen = useRef(scope);
  if (seen.current !== scope) {
    // a new level is framed afresh; the angle you chose is kept
    seen.current = scope;
    Object.assign(view.current, { zoom: 1, px: 0, py: 0 });
  }
  const [, redraw] = useState(0);

  const sheets = useMemo(() => build(scope), [scope]);
  const byScope = useMemo(() => new Map(sheets.map((s) => [s.scope, s])), [sheets]);
  const here = sheets.find((s) => s.role === "here")!;
  const below = sheets.some((s) => s.role === "below");

  // what the camera looks at: the middle of the current sheet and the staircase below it
  const ext = { x0: Infinity, x1: -Infinity, y0: Infinity, y1: -Infinity };
  for (const sh of sheets) {
    if (sh.role === "above") continue;
    const b = layoutOf(sh.scope).box;
    ext.x0 = Math.min(ext.x0, sh.ox + sh.s * (b.x - PADDING));
    ext.x1 = Math.max(ext.x1, sh.ox + sh.s * (b.x + b.w + PADDING));
    ext.y0 = Math.min(ext.y0, sh.oy + sh.s * (b.y - PADDING));
    ext.y1 = Math.max(ext.y1, sh.oy + sh.s * (b.y + b.h + PADDING));
  }
  const centre = { x: (ext.x0 + ext.x1) / 2, y: (ext.y0 + ext.y1) / 2, z: here.z - (below ? GAP * 0.5 : 0) };
  const W = ext.x1 - ext.x0, D = ext.y1 - ext.y0;
  const turn = (HOME.rz * Math.PI) / 180, tilt = (HOME.rx * Math.PI) / 180;
  const onScreen = {
    w: W * Math.cos(turn) + D * Math.abs(Math.sin(turn)),
    h: (W * Math.abs(Math.sin(turn)) + D * Math.cos(turn)) * Math.cos(tilt) + (below ? GAP : 0) * Math.sin(tilt),
  };
  const fit = vp.w ? Math.min(1.1, Math.min((vp.w - 40) / onScreen.w, (vp.h - 70) / onScreen.h) * 1.12) : 0.5;

  const paint = () => {
    const el = world.current;
    if (!el) return;
    const v = view.current;
    el.style.transform = `translate(${v.px}px, ${v.py}px) scale(${fit * v.zoom}) rotateX(${v.rx}deg) rotateZ(${v.rz}deg) translate3d(${-centre.x}px, ${-centre.y}px, ${-centre.z}px)`;
  };
  useLayoutEffect(paint);

  useLayoutEffect(() => {
    const el = wrap.current!;
    const ro = new ResizeObserver(() => setVp({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setVp({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // tell whoever asked for this scope (an answer, the breadcrumb) once the sheets have moved
  useEffect(() => {
    const t = window.setTimeout(arrived, 760 * motion());
    return () => window.clearTimeout(t);
  }, [scope]);

  useEffect(() => {
    const el = wrap.current!;
    const onWheel = (ev: WheelEvent) => {
      if ((ev.target as HTMLElement).closest(".node-panel")) return;
      if (window.scrollY > 4) return;
      const v = view.current;
      if (ev.deltaY > 0 && v.zoom <= 0.6) return; // fully out: let the page scroll
      ev.preventDefault();
      const unit = ev.deltaMode === 1 ? 16 : 1;
      const next = Math.min(4, Math.max(0.6, v.zoom * Math.exp(-ev.deltaY * unit * (ev.ctrlKey ? 0.012 : 0.0022))));
      // keep what is under the cursor under the cursor
      const rect = el.getBoundingClientRect();
      const cx = ev.clientX - rect.left - rect.width / 2, cy = ev.clientY - rect.top - rect.height / 2;
      const f = next / v.zoom;
      v.px = cx - (cx - v.px) * f;
      v.py = cy - (cy - v.py) * f;
      v.zoom = next;
      if (next <= 0.61) v.px = v.py = 0;
      el.classList.add("is-turning");
      paint();
      window.clearTimeout(idle.current);
      idle.current = window.setTimeout(() => el.classList.remove("is-turning"), 140);
      if (!getState().touched) set({ touched: true });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  });
  const idle = useRef(0);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key !== "Escape" || getState().jump) return;
      if (getState().selected && getState().panel) (clearThread("panel"), select(null));
      else goUp();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const drag = useRef<null | { id: number; x: number; y: number; moved: boolean; target: HTMLElement }>(null);
  const onPointerDown = (ev: React.PointerEvent) => {
    if ((ev.target as HTMLElement).closest(".node-panel, .canvas-ui")) return;
    drag.current = { id: ev.pointerId, x: ev.clientX, y: ev.clientY, moved: false, target: ev.target as HTMLElement };
  };
  const onPointerMove = (ev: React.PointerEvent) => {
    const d = drag.current;
    if (!d || d.id !== ev.pointerId) return;
    const dx = ev.clientX - d.x, dy = ev.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 5) return;
    if (!d.moved) {
      d.moved = true;
      wrap.current!.setPointerCapture(ev.pointerId);
      wrap.current!.classList.add("is-panning", "is-turning");
    }
    const v = view.current;
    if (ev.shiftKey || ev.buttons === 4) {
      v.px += dx;
      v.py += dy;
    } else {
      v.rz = Math.min(75, Math.max(-75, v.rz + dx * 0.25));
      v.rx = Math.min(80, Math.max(18, v.rx - dy * 0.25));
    }
    d.x = ev.clientX;
    d.y = ev.clientY;
    paint();
  };
  const onPointerUp = () => {
    const d = drag.current;
    drag.current = null;
    wrap.current!.classList.remove("is-panning", "is-turning");
    if (!d || d.moved) return;
    const sheet = d.target.closest<HTMLElement>("[data-sheet]")?.dataset.sheet;
    if (sheet && sheet !== scope) return void goTo(sheet);
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
    const t = ev.target as HTMLElement;
    const sheet = t.closest<HTMLElement>("[data-sheet]")?.dataset.sheet;
    // over a sheet below, light up the step it belongs to
    const id = sheet && sheet !== scope ? (byScope.get(sheet)?.from?.sheet === scope ? byScope.get(sheet)!.from!.node : null) : (t.closest<HTMLElement>("[data-id]")?.dataset.id ?? null);
    if (id !== getState().hover) set({ hover: id });
  };

  const reset = () => {
    view.current = { ...HOME, zoom: 1, px: 0, py: 0 };
    redraw((n) => n + 1);
  };
  const up = parentScope(scope);
  const panelNode = selected && panelOn ? selected : null;

  return (
    <div
      ref={wrap}
      className="canvas space"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onPointerOver={onOver}
      onPointerLeave={() => getState().hover && set({ hover: null })}
      onDoubleClick={onDoubleClick}
    >
      <svg width="0" height="0" className="defs" aria-hidden>
        <defs>
          <marker id="arr" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
            <path d="M1 1 9 5 1 9z" fill="context-stroke" />
          </marker>
        </defs>
      </svg>
      <div className="space-eye">
        <div ref={world} className="space-world">
          {sheets.map((sh) => {
            const l = layoutOf(sh.scope);
            const b = l.box;
            const opacity = sh.role === "above" ? Math.max(0.16, 0.62 - (sh.far - 1) * 0.2) : 1;
            const lit = sh.role === "below" && sh.from?.node === hover;
            return (
              <div
                key={sh.scope}
                data-sheet={sh.scope}
                className={`layer sheet is-${sh.role}${sh.s * fit < 0.62 ? " is-far" : ""}${lit ? " is-lit" : ""}`}
                style={{
                  transform: `translate3d(${sh.ox}px, ${sh.oy}px, ${sh.z}px) scale(${sh.s})`,
                  opacity,
                  ["--lod" as string]: Math.min(2.5, Math.max(1, 0.8 / (sh.s * fit))),
                }}
              >
                <div className="sheet-glass" style={{ left: b.x - PADDING, top: b.y - PADDING, width: b.w + PADDING * 2, height: b.h + PADDING * 2 }} />
                <div className="sheet-name" style={{ left: b.x - PADDING, top: b.y - PADDING }}>
                  {node(sh.scope).title}
                </div>
                <ScopeLayer layout={l} selected={sh.role === "here" ? selected : null} hover={sh.role === "here" ? hover : null} highlight={highlight} />
              </div>
            );
          })}
          {sheets.map((sh) => {
            const parent = sh.from ? byScope.get(sh.from.sheet) : null;
            const r = parent && sh.from ? layoutOf(parent.scope).byId[sh.from.node] : null;
            if (!parent || !r) return null;
            const top = corners(parent, r);
            const bottom = corners(sh, layoutOf(sh.scope).box, PADDING);
            const tone = toneOf(node(sh.from!.node));
            return top.map((a, i) => (
              <Beam key={`${sh.scope}:${scope}:${i}`} a={a} b={bottom[i]} tone={tone} faint={sh.role === "below" && sh.from!.node !== hover} />
            ));
          })}
        </div>
      </div>

      <div className={`panel-anchor${panelNode ? " is-open" : ""}`} data-mode="corner">
        {panelNode && <NodePanel key={panelNode} id={panelNode} onResize={() => {}} />}
      </div>

      <div className="canvas-ui bottom-left">
        <div className="zoom">
          <button className="fit" onClick={reset}>Reset view</button>
        </div>
        {up && (
          <button className="up" onClick={goUp}>
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden><path d="M2.5 7 6 3.5 9.5 7M6 3.5V10" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
            Up to {node(up).title}
          </button>
        )}
      </div>
      <div className="canvas-ui hint static">
        <b>Drag</b> to turn · <b>Shift-drag</b> to move · <b>scroll</b> to zoom · <b>click a sheet</b> to go to that level{scope === ROOT ? "" : " · Esc goes up"}
      </div>
    </div>
  );
}
