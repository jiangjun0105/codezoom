import { crumbs, levelOf, node } from "../lib/graph";
import { goTo, useStore } from "../store";

export function Breadcrumb() {
  const scope = useStore((s) => s.scope);
  const all = crumbs(scope);
  const shown = all.length > 5 ? [all[0], null, ...all.slice(-3)] : all;
  return (
    <nav className="crumbs" aria-label="Zoom path">
      {shown.map((c, i) =>
        c === null ? (
          <span key="gap" className="gap" title={all.slice(1, -3).map((x) => x.title).join(" › ")}>…</span>
        ) : (
          <span key={c.id} className="crumb-wrap">
            {i > 0 && <span className="sep">›</span>}
            <button
              className={`crumb${c.id === all[all.length - 1].id ? " here" : ""}${node(c.id).type === "call" ? " fn" : ""}`}
              onClick={() => void goTo(c.target)}
              disabled={c.target === scope}
              title={node(c.id).label}
            >
              {c.title}
            </button>
          </span>
        ),
      )}
      <span className="level">Level {all.length - 1} · {levelOf(scope).name}</span>
    </nav>
  );
}
