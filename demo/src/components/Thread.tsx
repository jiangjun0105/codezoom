import { useEffect, useRef, useState } from "react";
import type { Suggestion } from "../lib/answers";
import { ask, useLive, useThread, type Msg, type ThreadName } from "../lib/ask";
import { hasNode, node } from "../lib/graph";
import { runAction, useStore, type Action } from "../store";
import { Rich } from "./Rich";

function actionText(a: Action): string {
  if (a.tool === "highlight_path") return `highlight_path(${a.ids.length} node${a.ids.length === 1 ? "" : "s"})`;
  return `${a.tool}(${hasNode(a.id) ? node(a.id).title : a.id})`;
}

const SOURCE: Record<string, string> = {
  authored: "Pre-computed answer",
  derived: "Pre-computed from the 2023 labels and call graph",
  live: "Live answer",
};

function Agent({ m }: { m: Msg }) {
  return (
    <div className="msg agent">
      {m.actions && m.actions.length > 0 && (
        <div className="tools">
          {m.actions.map((a, i) => {
            const state = (m.done ?? 0) > i ? "done" : (m.done ?? 0) === i && m.status === "acting" ? "run" : "wait";
            return (
              <button key={i} className={`tool ${state}`} onClick={() => void runAction(a)} disabled={m.status !== "done"} title="Run again">
                <span className="tool-mark" />
                {actionText(a)}
              </button>
            );
          })}
        </div>
      )}
      {m.status === "thinking" ? (
        <div className="dots"><i /><i /><i /></div>
      ) : (
        <div className={`rich${m.status === "typing" ? " typing" : ""}`}>
          <Rich text={m.text} />
        </div>
      )}
      {m.status === "done" && m.source && SOURCE[m.source] && <div className="msg-source">{SOURCE[m.source]}</div>}
    </div>
  );
}

export function Thread(props: {
  name: ThreadName;
  nodeId: string | null;
  suggestions: Suggestion[];
  placeholder: string;
  onChange?: () => void;
  compact?: boolean;
}) {
  const { name, nodeId, suggestions } = props;
  const msgs = useThread(name);
  const live = useLive();
  const driving = useStore((s) => s.driving);
  const [draft, setDraft] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  const busy = msgs.some((m) => m.role === "agent" && m.status !== "done") || driving;

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
    props.onChange?.();
  });

  const send = (q: string, known?: Suggestion) => {
    if (busy) return;
    setDraft("");
    void ask(name, q, nodeId, known);
  };
  const asked = new Set(msgs.filter((m) => m.role === "user").map((m) => m.text));
  const open = suggestions.filter((s) => !asked.has(s.q));
  const offers = msgs[msgs.length - 1]?.offers;

  return (
    <div className={`thread${props.compact ? " compact" : ""}`}>
      {msgs.length > 0 && (
        <div className="msgs" ref={scroller}>
          {msgs.map((m) =>
            m.role === "user" ? (
              <div key={m.id} className="msg user">
                {m.about && name === "panel" && nodeId && node(nodeId).title !== m.about && <span className="about">{m.about}</span>}
                {m.text}
              </div>
            ) : (
              <Agent key={m.id} m={m} />
            ),
          )}
        </div>
      )}
      {(offers ?? open.map((s) => s.q)).length > 0 && (
        <div className="chips">
          {offers
            ? offers.map((q) => (
                <button key={q} className="chip" disabled={busy} onClick={() => send(q, suggestions.find((s) => s.q === q))}>{q}</button>
              ))
            : open.map((s) => (
                <button key={s.q} className="chip" disabled={busy} onClick={() => send(s.q, s)}>{s.q}</button>
              ))}
        </div>
      )}
      <form
        className="ask"
        onSubmit={(e) => {
          e.preventDefault();
          send(draft, suggestions.find((s) => s.q.toLowerCase() === draft.trim().toLowerCase()));
        }}
      >
        <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={props.placeholder} aria-label={props.placeholder} maxLength={400} />
        <button type="submit" disabled={busy || !draft.trim()} aria-label="Ask">
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden><path d="M2 7h9.5M7.5 2.5 12 7l-4.500 4.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </button>
      </form>
      <div className="mode">{live ? "Live mode: typed questions go to a model" : "No model attached: answers are pre-computed"}</div>
    </div>
  );
}
