import { useEffect, useMemo, useRef, useState } from "react";
import { canEnter, crumbs, displayOf, graph, node, shortFn, type GNode } from "../lib/graph";
import { focusNode, set, useStore } from "../store";
import { tagOf, toneOf } from "./Canvas";

interface Entry {
  n: GNode;
  title: string;
  label: string;
  fn: string;
  code: string;
}

const entries: Entry[] = Object.values(graph.nodes)
  .filter((n) => n.parent !== null)
  .map((n) => ({
    n,
    title: n.title.toLowerCase(),
    label: n.label.toLowerCase(),
    fn: shortFn(n.fn).toLowerCase(),
    code: (n.code ?? "").toLowerCase(),
  }));

/** Every word must appear somewhere; a hit in the title counts most, named blocks and calls come first. */
function search(q: string): GNode[] {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const scored: [number, GNode][] = [];
  for (const e of entries) {
    let score = 0;
    for (const w of words) {
      const s = e.title.includes(w) ? 6 : e.fn.includes(w) ? 3 : e.label.includes(w) ? 2 : e.code.includes(w) ? 1 : 0;
      if (!s) {
        score = 0;
        break;
      }
      score += s;
    }
    if (!score) continue;
    if (e.n.kind === "group") score += 3;
    else if (canEnter(e.n.id)) score += 2;
    if (e.title.startsWith(words[0])) score += 2;
    scored.push([score, e.n]);
  }
  return scored.sort((a, b) => b[0] - a[0]).slice(0, 9).map((s) => s[1]);
}

const where = (id: string) =>
  crumbs(displayOf(id).scope)
    .map((c) => c.title)
    .join(" › ");

export function Jump() {
  const open = useStore((s) => s.jump);
  const [q, setQ] = useState("");
  const [at, setAt] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const hits = useMemo(() => search(q), [q]);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      const typing = /^(INPUT|TEXTAREA)$/.test((ev.target as HTMLElement).tagName);
      if ((ev.key === "k" && (ev.metaKey || ev.ctrlKey)) || (ev.key === "/" && !typing)) {
        ev.preventDefault();
        set({ jump: true });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!open) return;
    setQ("");
    setAt(0);
    input.current?.focus();
  }, [open]);

  if (!open) return null;
  const close = () => set({ jump: false });
  const go = (n: GNode | undefined) => {
    if (!n) return;
    close();
    void focusNode(n.id);
  };

  return (
    <div className="jump-veil" onPointerDown={(e) => e.target === e.currentTarget && close()}>
      <div className="jump" role="dialog" aria-label="Jump to a step">
        <input
          ref={input}
          value={q}
          placeholder="Jump to a step, a function, or a line of code…"
          onChange={(e) => (setQ(e.target.value), setAt(0))}
          onKeyDown={(e) => {
            if (e.key === "Escape") (e.stopPropagation(), close());
            else if (e.key === "ArrowDown") (e.preventDefault(), setAt((i) => Math.min(hits.length - 1, i + 1)));
            else if (e.key === "ArrowUp") (e.preventDefault(), setAt((i) => Math.max(0, i - 1)));
            else if (e.key === "Enter") go(hits[at]);
          }}
        />
        {q.trim() === "" ? (
          <p className="jump-empty">
            Try <button onClick={() => setQ("prompt")}>prompt</button> <button onClick={() => setQ("memory")}>memory</button>{" "}
            <button onClick={() => setQ("execute command")}>execute command</button> <button onClick={() => setQ("api key")}>api key</button>
          </p>
        ) : hits.length === 0 ? (
          <p className="jump-empty">Nothing in this run matches “{q}”.</p>
        ) : (
          <ul>
            {hits.map((n, i) => (
              <li key={n.id}>
                <button className={`jump-hit tone-${toneOf(n)}${i === at ? " on" : ""}`} onPointerEnter={() => setAt(i)} onClick={() => go(n)}>
                  <span className="jump-tag">{tagOf(n)}</span>
                  <span className="jump-main">
                    <span className={n.kind === "group" ? "jump-title named" : "jump-title"}>{n.title}</span>
                    <span className="jump-label">{node(n.id).label}</span>
                  </span>
                  <span className="jump-where">{where(n.id)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
