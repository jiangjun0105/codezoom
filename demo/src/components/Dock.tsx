import { useEffect, useMemo, useRef } from "react";
import { programSuggestions } from "../lib/answers";
import { clearThread } from "../lib/ask";
import { ROOT, fnInfo, modulePath, node, scopeFn } from "../lib/graph";
import { tokenizeLines } from "../lib/python";
import { select, set, useStore } from "../store";
import { Thread } from "./Thread";

/** The function behind the current chart, with the lines of each step marked. */
function Source() {
  const scope = useStore((s) => s.scope);
  const selected = useStore((s) => s.selected);
  const hover = useStore((s) => s.hover);
  const uri = scopeFn(scope);
  const info = fnInfo(uri);
  const body = useRef<HTMLDivElement>(null);
  const lines = useMemo(() => tokenizeLines(info?.code ?? ""), [info]);

  // which step of the current chart each line belongs to (the tightest one wins)
  const owner = useMemo(() => {
    const map = new Map<number, string>();
    const kids = node(scope)
      .children.filter((c) => node(c).fn === uri && node(c).lines)
      .sort((a, b) => node(b).lines![1] - node(b).lines![0] - (node(a).lines![1] - node(a).lines![0]));
    for (const c of kids) for (let l = node(c).lines![0]; l <= node(c).lines![1]; l++) map.set(l, c);
    return map;
  }, [scope, uri]);

  const active = [hover, selected].find((id) => id && node(id) && node(id).fn === uri && node(id).lines) ?? null;
  const range = active ? node(active).lines! : null;
  const scopeNode = node(scope);
  const within = scopeNode.fn === uri && scopeNode.lines && scope !== ROOT ? scopeNode.lines : null;

  useEffect(() => {
    const first = range?.[0] ?? within?.[0];
    const el = body.current;
    if (!el) return;
    if (!first) {
      el.scrollTo({ top: 0 });
      return;
    }
    const row = el.querySelector<HTMLElement>(`[data-line="${first}"]`);
    if (!row) return;
    const top = row.offsetTop, h = el.clientHeight;
    if (top < el.scrollTop + 24 || top > el.scrollTop + h - 72) el.scrollTo({ top: Math.max(0, top - h * 0.3), behavior: "smooth" });
  }, [range?.[0], within?.[0], uri]);

  if (!info?.code) return <div className="source-empty">No source was cached for this function.</div>;
  return (
    <div className="source">
      <div className="source-head">
        <span className="path">{modulePath(uri)}</span>
        <span className="fn">{info.name}</span>
        {info.fileLine ? <span className="at">line {info.fileLine}</span> : null}
      </div>
      <div className="source-body" ref={body} onPointerLeave={() => set({ hover: null })}>
        {lines.map((toks, i) => {
          const no = i + 1;
          const own = owner.get(no);
          const on = range && no >= range[0] && no <= range[1];
          const off = within && (no < within[0] || no > within[1]);
          return (
            <div
              key={no}
              data-line={no}
              className={`src-line${on ? " on" : ""}${off ? " off" : ""}${own ? " has" : ""}`}
              onPointerEnter={() => own && set({ hover: own })}
              onClick={() => own && (clearThread("panel"), select(own))}
            >
              <span className="no">{no}</span>
              <span className="tx">{toks.length ? toks.map(([cls, t], j) => (cls ? <span key={j} className={`t-${cls}`}>{t}</span> : t)) : " "}</span>
            </div>
          );
        })}
      </div>
      <div className="source-foot">Line numbers follow the parsed source the pipeline worked on, so formatting differs slightly from the file.</div>
    </div>
  );
}

export function Dock() {
  const dock = useStore((s) => s.dock);
  if (!dock) return null;
  return (
    <aside className="dock">
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={dock === "source"} onClick={() => set({ dock: "source" })}>Source</button>
        <button role="tab" aria-selected={dock === "ask"} onClick={() => set({ dock: "ask" })}>Ask the program</button>
        <button className="close" onClick={() => set({ dock: null })} aria-label="Close side panel">×</button>
      </div>
      {dock === "source" ? (
        <Source />
      ) : (
        <div className="ask-tab">
          <p className="ask-intro">
            Questions about the whole run. An answer can move the diagram: it calls <code>zoom_to_level</code>, <code>focus_node</code> and <code>highlight_path</code>.
          </p>
          <Thread name="dock" nodeId={null} suggestions={programSuggestions} placeholder="Ask about the program" />
        </div>
      )}
    </aside>
  );
}
