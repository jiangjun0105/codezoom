import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { suggestionsFor } from "../lib/answers";
import { clearThread, useThread } from "../lib/ask";
import { canEnter, fnInfo, modulePath, node, shortFn } from "../lib/graph";
import { openNode, select, set } from "../store";
import { linesOf, tagOf, toneOf } from "./Canvas";
import { Code } from "./Rich";
import { Thread } from "./Thread";

/** The panel that floats next to the selected node: what it is, its code, and a question box. */
export function NodePanel({ id, onResize }: { id: string; onResize: () => void }) {
  const n = node(id);
  const el = useRef<HTMLDivElement>(null);
  const suggestions = useMemo(() => suggestionsFor(id), [id]);
  const callee = n.callee ? fnInfo(n.callee) : undefined;
  const enterable = canEnter(id);
  const plain = n.type === "start" || n.type === "end";
  // once a conversation is under way, the answer gets the room
  const talking = useThread("panel").length > 0;

  useLayoutEffect(onResize);
  useEffect(() => {
    const ro = new ResizeObserver(onResize);
    if (el.current) ro.observe(el.current);
    return () => ro.disconnect();
  }, [onResize]);

  return (
    <div className={`node-panel tone-${toneOf(n)}`} ref={el} role="dialog" aria-label={n.title}>
      <header>
        <span className="card-tag">
          <span className="glyph" />
          {n.kind === "stage" ? "Step" : tagOf(n)}
        </span>
        <span className="where">
          {shortFn(n.fn)} {linesOf(n)}
        </span>
        <button className="close" onClick={() => (clearThread("panel"), select(null))} aria-label="Close">×</button>
      </header>
      <div className="panel-body">
        <h3>{n.kind === "stage" ? n.title : n.label}</h3>
        {n.kind === "stage" && <p className="summary">{n.label}</p>}
        {callee && (
          <p className="callee">
            calls <code>{callee.name}</code>
            {callee.code ? <> in <code>{modulePath(callee.uri)}</code></> : " (outside the analysed code)"}
          </p>
        )}
        {n.code && !plain && !talking && (
          <button className="code-wrap" onClick={() => set({ dock: "source", hover: id })} title="Show in the Source tab">
            <Code code={n.code} maxLines={5} />
          </button>
        )}
        {enterable && !talking && (
          <button className="open-btn" onClick={() => openNode(id)}>
            Zoom in to this step
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden><path d="M4 2.5 7.5 6 4 9.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </button>
        )}
        {!plain && <Thread name="panel" nodeId={id} suggestions={suggestions} placeholder="Ask about this step" onChange={onResize} compact />}
      </div>
    </div>
  );
}
