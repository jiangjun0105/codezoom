import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { canEnter, graph, lineage, node, type GNode } from "../lib/graph";
import { focusNode, getState, set, useStore } from "../store";
import { tagOf, toneOf } from "./Canvas";

/*
 * Every level at once, as floors of a pyramid. The top floor is the program as one box;
 * each floor below holds every box of the next level, placed under the box that contains
 * it. A box is as wide as the share of the program's statements it holds, so the floors
 * widen towards the bottom, and a branch that ends early leaves a gap in the floors below:
 * you see at a glance where the program is deep and where it is shallow.
 */

const GAP = 128; // height between floors
const ROW = 150; // depth of a floor
const TOP_W = 420; // width of the top floor
const BOTTOM_W = 2100; // width of the deepest floor
const HOME = { rx: 50, rz: -5 };
const LIFT = 46; // room for the caption above the top floor

const NAMES = ["System", "Main flow", "Processes", "Parts"];
const floorName = (d: number, leavesOnly: boolean) => (leavesOnly && d > 2 ? "Code" : (NAMES[d] ?? "Steps"));

interface Tile {
  id: string;
  floor: number;
  x: number; // left edge, floor coordinates (centred on 0)
  w: number;
}

const MAIN = graph.meta.main;

function weight(id: string, memo: Map<string, number>): number {
  const hit = memo.get(id);
  if (hit !== undefined) return hit;
  const kids = graph.nodes[id].children;
  const w = kids.length ? kids.reduce((s, k) => s + weight(k, memo), 0) : 1;
  memo.set(id, w);
  return w;
}

/** Lay out every node below the system box: floor 0 is the program, floor d its depth-d descendants. */
function build() {
  const memo = new Map<string, number>();
  const total = weight(MAIN, memo);
  const tiles: Tile[] = [];
  let floors = 0;
  const widthAt = (d: number) => TOP_W + (BOTTOM_W - TOP_W) * Math.min(1, d / Math.max(1, floors - 1));
  // first pass: depth
  const depthOf = (id: string, d: number): void => {
    floors = Math.max(floors, d + 1);
    graph.nodes[id].children.forEach((k) => depthOf(k, d + 1));
  };
  depthOf(MAIN, 0);
  // second pass: each node spans its share of statements, measured from the left of its floor
  const place = (id: string, d: number, before: number) => {
    const share = weight(id, memo) / total;
    const W = widthAt(d);
    tiles.push({ id, floor: d, x: -W / 2 + (before / total) * W, w: share * W });
    let acc = before;
    for (const k of graph.nodes[id].children) {
      place(k, d + 1, acc);
      acc += weight(k, memo);
    }
  };
  place(MAIN, 0, 0);
  const perFloor = Array.from({ length: floors }, (_, d) => tiles.filter((t) => t.floor === d));
  return { tiles, floors, perFloor, widthAt, total, byId: new Map(tiles.map((t) => [t.id, t])) };
}

const zOf = (floor: number, floors: number) => ((floors - 1) / 2 - floor) * GAP;

function descendants(id: string, out: Set<string>) {
  for (const k of graph.nodes[id].children) {
    out.add(k);
    descendants(k, out);
  }
  return out;
}

export function Pyramid() {
  const scope = useStore((s) => s.scope);
  const P = useMemo(build, []);
  const wrap = useRef<HTMLDivElement>(null);
  const world = useRef<HTMLDivElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  const [vp, setVp] = useState({ w: 0, h: 0 });
  const [hover, setHover] = useState<string | null>(null);
  const view = useRef({ ...HOME, zoom: 1, px: 0, py: LIFT });
  const idle = useRef(0);

  // what is lit: the hovered box, everything above it and everything inside it; else the chart you were in
  const lit = useMemo(() => {
    const focus = hover ?? scope;
    const s = new Set(lineage(focus));
    if (hover) descendants(hover, s);
    else node(scope).children.forEach((k) => s.add(k));
    return s;
  }, [hover, scope]);

  const tilt = (HOME.rx * Math.PI) / 180;
  const fit = vp.w ? Math.min((vp.w - 60) / (BOTTOM_W * 1.02), (vp.h - 170) / ((P.floors - 1) * GAP * Math.sin(tilt) + ROW * Math.cos(tilt) * 2.4)) : 0.4;

  const paint = () => {
    const el = world.current;
    if (!el) return;
    const v = view.current;
    el.style.transform = `translate(${v.px}px, ${v.py}px) scale(${fit * v.zoom}) rotateX(${v.rx}deg) rotateZ(${v.rz}deg)`;
  };
  useLayoutEffect(paint);

  useLayoutEffect(() => {
    const el = wrap.current!;
    const ro = new ResizeObserver(() => setVp({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setVp({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const el = wrap.current!;
    const onWheel = (ev: WheelEvent) => {
      if (window.scrollY > 4) return;
      const v = view.current;
      if (ev.deltaY > 0 && v.zoom <= 0.7) return; // fully out: let the page scroll
      ev.preventDefault();
      const unit = ev.deltaMode === 1 ? 16 : 1;
      const next = Math.min(6, Math.max(0.7, v.zoom * Math.exp(-ev.deltaY * unit * (ev.ctrlKey ? 0.012 : 0.0022))));
      const rect = el.getBoundingClientRect();
      const cx = ev.clientX - rect.left - rect.width / 2, cy = ev.clientY - rect.top - rect.height / 2;
      const f = next / v.zoom;
      v.px = cx - (cx - v.px) * f;
      v.py = cy - (cy - v.py) * f;
      v.zoom = next;
      el.classList.add("is-turning");
      paint();
      window.clearTimeout(idle.current);
      idle.current = window.setTimeout(() => el.classList.remove("is-turning"), 140);
      if (!getState().touched) set({ touched: true });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  });

  const drag = useRef<null | { id: number; x: number; y: number; moved: boolean; target: HTMLElement }>(null);
  const onPointerDown = (ev: React.PointerEvent) => {
    if ((ev.target as HTMLElement).closest(".canvas-ui")) return;
    drag.current = { id: ev.pointerId, x: ev.clientX, y: ev.clientY, moved: false, target: ev.target as HTMLElement };
  };
  const onPointerMove = (ev: React.PointerEvent) => {
    const t = tip.current;
    if (t) {
      const rect = wrap.current!.getBoundingClientRect();
      const x = ev.clientX - rect.left, y = ev.clientY - rect.top;
      t.style.transform = `translate(${Math.min(x + 16, rect.width - 330)}px, ${y + 18}px)`;
    }
    const d = drag.current;
    if (!d || d.id !== ev.pointerId) return;
    const dx = ev.clientX - d.x, dy = ev.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 5) return;
    if (!d.moved) {
      d.moved = true;
      wrap.current!.setPointerCapture(ev.pointerId);
      wrap.current!.classList.add("is-panning", "is-turning");
      setHover(null);
    }
    const v = view.current;
    if (ev.shiftKey || ev.buttons === 4) {
      v.px += dx;
      v.py += dy;
    } else {
      v.rz = Math.min(80, Math.max(-80, v.rz + dx * 0.25));
      v.rx = Math.min(84, Math.max(10, v.rx - dy * 0.25));
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
    const id = d.target.closest<HTMLElement>("[data-tile]")?.dataset.tile;
    if (!id) return;
    // open the box in the zoomable view, where it can be read and asked about
    set({ mode: "flat" });
    window.setTimeout(() => void focusNode(id), 60);
  };
  const onOver = (ev: React.PointerEvent) => {
    if (drag.current?.moved) return;
    const id = (ev.target as HTMLElement).closest<HTMLElement>("[data-tile]")?.dataset.tile ?? null;
    if (id !== hover) setHover(id);
  };

  const reset = () => {
    view.current = { ...HOME, zoom: 1, px: 0, py: LIFT };
    paint();
  };

  const h = hover ? node(hover) : null;
  const hTile = hover ? P.byId.get(hover) : null;

  return (
    <div
      ref={wrap}
      className={`canvas space pyramid${hover ? " is-hovering" : ""}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onPointerOver={onOver}
      onPointerLeave={() => setHover(null)}
    >
      <div className="space-eye">
        <div ref={world} className="space-world">
          {P.perFloor.map((tiles, d) => {
            const W = P.widthAt(d);
            const leavesOnly = tiles.every((t) => !graph.nodes[t.id].children.length);
            return (
              <div key={d} className="pyr-floor" style={{ transform: `translate3d(0, ${-ROW / 2}px, ${zOf(d, P.floors)}px)` }}>
                <div className="pyr-slab" style={{ left: -W / 2 - 14, width: W + 28, height: ROW + 20, top: -10 }} />
                <div className="pyr-name" style={{ left: -W / 2 - 26 }}>
                  <b>Level {d}</b> · {floorName(d, leavesOnly)}
                  <span>{tiles.length} {tiles.length === 1 ? "box" : "boxes"}</span>
                </div>
                {tiles.map((t) => {
                  const n = graph.nodes[t.id];
                  const on = lit.has(t.id);
                  return (
                    <div
                      key={t.id}
                      data-tile={t.id}
                      className={`pyr-tile tone-${toneOf(n)}${on ? " is-on" : ""}${t.id === hover ? " is-hover" : ""}${n.children.length ? "" : " is-leaf"}`}
                      style={{ left: t.x, width: Math.max(1.5, t.w - (t.w > 6 ? 3 : 0.5)), height: ROW }}
                    >
                      {t.w > 90 && <span>{n.title}</span>}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>

      <div ref={tip} className={`pyr-tip${h ? " is-on" : ""}`} aria-hidden>
        {h && hTile && (
          <>
            <div className="pyr-tip-tag">
              Level {hTile.floor} · {floorName(hTile.floor, !h.children.length && hTile.floor > 2)} · {tagOf(h as GNode)}
              {h.children.length > 0 && <span> · {weightLabel(hover!)}</span>}
            </div>
            <div className="pyr-tip-title">{h.title}</div>
            <div className="pyr-tip-label">{h.label}</div>
            <div className="pyr-tip-go">Click to open it{canEnter(h.id) ? " and zoom in" : ""}</div>
          </>
        )}
      </div>

      <div className="canvas-ui caption">
        <div className="cap-kicker">
          Whole structure<span>every level at once</span>
        </div>
        <div className="cap-title">
          {P.floors} levels · {P.tiles.length} boxes · {P.total} statements
        </div>
        <div className="cap-text">
          Each floor is one level of the zoomable chart. A box is as wide as the share of statements it holds and sits over the boxes inside it; gaps show
          where a branch ends early.
        </div>
      </div>
      <div className="canvas-ui bottom-left">
        <div className="zoom">
          <button className="fit" onClick={reset}>Reset view</button>
        </div>
      </div>
      <div className="canvas-ui hint static">
        <b>Point</b> at a box to trace it up and down · <b>click</b> to open it · <b>drag</b> to turn · <b>scroll</b> to zoom
      </div>
    </div>
  );
}

function weightLabel(id: string): string {
  let n = 0;
  const walk = (x: string) => {
    const kids = graph.nodes[x].children;
    if (!kids.length) n++;
    kids.forEach(walk);
  };
  walk(id);
  return `${n} statement${n === 1 ? "" : "s"} inside`;
}
