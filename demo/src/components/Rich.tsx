import { Fragment, memo } from "react";
import { hasNode } from "../lib/graph";
import { tokenizeLines } from "../lib/python";
import { focusNode } from "../store";

/** Inline: `code`, **bold** and [[nodeId|text]] links that move the diagram. */
function inline(text: string, key: string) {
  const parts = text.split(/(\[\[[^\]]+\]\]|`[^`]+`|\*\*[^*]+\*\*)/g);
  return parts.map((p, i) => {
    const k = `${key}:${i}`;
    if (p.startsWith("[[") && p.endsWith("]]")) {
      const bar = p.indexOf("|");
      const id = p.slice(2, bar < 0 ? -2 : bar);
      const label = bar < 0 ? id : p.slice(bar + 1, -2);
      if (!hasNode(id)) return <Fragment key={k}>{inline(label, k)}</Fragment>;
      return (
        <button key={k} className="node-link" onClick={() => void focusNode(id)} title="Show in the diagram">
          {inline(label, k)}
        </button>
      );
    }
    if (p.startsWith("`") && p.endsWith("`") && p.length > 2) return <code key={k}>{p.slice(1, -1)}</code>;
    if (p.startsWith("**") && p.endsWith("**") && p.length > 4) return <b key={k}>{p.slice(2, -2)}</b>;
    return <Fragment key={k}>{p}</Fragment>;
  });
}

export const Rich = memo(function Rich({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/);
  return (
    <>
      {blocks.map((b, i) => {
        const lines = b.split("\n");
        const items = lines.filter((l) => l.startsWith("- "));
        const lead = lines.filter((l) => !l.startsWith("- ")).join(" ");
        return (
          <Fragment key={i}>
            {lead && <p>{inline(lead, `p${i}`)}</p>}
            {items.length > 0 && (
              <ul>
                {items.map((l, j) => (
                  <li key={j}>{inline(l.slice(2), `l${i}.${j}`)}</li>
                ))}
              </ul>
            )}
          </Fragment>
        );
      })}
    </>
  );
});

export const Code = memo(function Code({ code, maxLines }: { code: string; maxLines?: number }) {
  const all = tokenizeLines(code);
  const lines = maxLines && all.length > maxLines ? all.slice(0, maxLines) : all;
  return (
    <pre className="code">
      {lines.map((toks, i) => (
        <div key={i} className="code-line">
          {toks.length ? toks.map(([cls, t], j) => (cls ? <span key={j} className={`t-${cls}`}>{t}</span> : t)) : " "}
        </div>
      ))}
      {lines.length < all.length && <div className="code-more">… {all.length - lines.length} more lines in the Source tab</div>}
    </pre>
  );
});
