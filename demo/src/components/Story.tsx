import { LINKS } from "../App";
import { graph } from "../lib/graph";

const STEPS = [
  {
    name: "Call graph",
    text: "Static analysis from the entry point finds every function the run can reach, and who calls whom.",
    file: "parser/callgraph.py",
    art: (
      <svg viewBox="0 0 120 64" aria-hidden>
        <g className="a-line"><path d="M22 14 60 32M22 50 60 32M60 32 98 14M60 32 98 50M98 14v36" /></g>
        <g className="a-node"><circle cx="22" cy="14" r="5" /><circle cx="22" cy="50" r="5" /><circle cx="98" cy="14" r="5" /><circle cx="98" cy="50" r="5" /></g>
        <circle className="a-hot" cx="60" cy="32" r="6.500" />
      </svg>
    ),
  },
  {
    name: "Syntax-tree flowcharts",
    text: "Each function's syntax tree becomes start, action, call, decision and end nodes, nested the way the code is.",
    file: "flowchart/ast_process.py",
    art: (
      <svg viewBox="0 0 120 64" aria-hidden>
        <g className="a-line"><path d="M60 14v8M48 34H30v8M72 34h18v8" /></g>
        <rect className="a-node" x="44" y="4" width="32" height="10" rx="3" />
        <path className="a-hot" d="m60 22 12 12-12 12-12-12z" />
        <rect className="a-node" x="14" y="42" width="32" height="10" rx="3" />
        <rect className="a-node" x="74" y="42" width="32" height="10" rx="3" />
      </svg>
    ),
  },
  {
    name: "LLM labels",
    text: "A language model reads each statement and writes one plain-English line. A block's label is then summarised from the labels inside it.",
    file: "flowchart/label.py",
    art: (
      <svg viewBox="0 0 120 64" aria-hidden>
        <rect className="a-node" x="16" y="10" width="88" height="44" rx="6" />
        <g className="a-line"><path d="M28 24h40M28 34h64M28 44h30" /></g>
        <circle className="a-hot" cx="90" cy="24" r="4" />
      </svg>
    ),
  },
  {
    name: "Rebalancing",
    text: "Thin wrapper levels are expanded away and long runs of steps are grouped into named blocks, so every level shows a handful of steps.",
    file: "codezoom/retree.py",
    art: (
      <svg viewBox="0 0 120 64" aria-hidden>
        <ellipse className="a-ring" cx="36" cy="32" rx="24" ry="22" />
        <ellipse className="a-ring" cx="88" cy="32" rx="22" ry="20" />
        <g className="a-node"><circle cx="28" cy="24" r="4" /><circle cx="44" cy="30" r="4" /><circle cx="32" cy="42" r="4" /><circle cx="82" cy="26" r="4" /></g>
        <circle className="a-hot" cx="94" cy="38" r="4.500" />
        <g className="a-line"><path d="M48 31h30" /></g>
      </svg>
    ),
  },
  {
    name: "Agents",
    text: "One agent per level: repository, package, module, function. Each answers from its own context and asks the level below.",
    file: "bots/",
    art: (
      <svg viewBox="0 0 120 64" aria-hidden>
        <rect className="a-node" x="10" y="6" width="100" height="11" rx="3" />
        <rect className="a-node" x="22" y="21" width="76" height="11" rx="3" />
        <rect className="a-node" x="34" y="36" width="52" height="11" rx="3" />
        <rect className="a-hot" x="46" y="51" width="28" height="9" rx="3" />
      </svg>
    ),
  },
];

export function Story() {
  const m = graph.meta as typeof graph.meta & {
    depth: number;
    groups: number;
    statementCount: number;
    repoCounts: Record<string, number>;
    shapeBefore: Record<string, number>;
    shapeAfter: Record<string, number>;
  };
  const fns = m.repoCounts.function + m.repoCounts.class_method;
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  const rows: [string, string, string][] = [
    ["Deepest statement", `${m.shapeBefore.max_depth} levels`, `${m.shapeAfter.max_depth} levels`],
    ["Average statement depth", m.shapeBefore.mean_depth.toFixed(1), m.shapeAfter.mean_depth.toFixed(1)],
    ["Charts with 3 to 8 steps", pct(m.shapeBefore.share_3_to_8), pct(m.shapeAfter.share_3_to_8)],
    ["Charts with 1 or 2 steps", String(m.shapeBefore.charts_with_2_or_fewer), String(m.shapeAfter.charts_with_2_or_fewer)],
    ["Widest chart", `${m.shapeBefore.widest} steps`, `${m.shapeAfter.widest} steps`],
  ];
  return (
    <div className="story" id="how">
      <section className="how">
        <p className="eyebrow">How it works</p>
        <h2>From source files to a map you can question</h2>
        <p className="lede">
          The pipeline takes a repository and one entry point. Nothing in the diagram above was drawn by hand: structure comes from static
          analysis, wording from a language model.
        </p>
        <ol className="pipeline">
          {STEPS.map((s, i) => (
            <li key={s.name}>
              <div className="art">{s.art}</div>
              <span className="num">{i + 1}</span>
              <h3>{s.name}</h3>
              <p>{s.text}</p>
              <code>{s.file}</code>
            </li>
          ))}
        </ol>
      </section>

      <section className="rebalance">
        <div>
          <p className="eyebrow">Step 4, up close</p>
          <h2>Code nests deep and thin. Understanding wants a few steps at a time.</h2>
          <p className="lede">
            Straight from the syntax tree, most charts hold one or two steps and the entry function holds {m.shapeBefore.widest}. The
            rebalancing pass keeps every statement and every edge and changes only how they are bundled: it expands a step when a chart is
            too small or lopsided, and groups a run of steps when a chart is too full. A group must have one way in and one way out, so it
            can be drawn as a single box.
          </p>
          <p className="lede">
            A language model proposes the groups and names them; a dynamic-programming segmenter takes over when its answer breaks that
            rule. The {m.groups} named groups in the diagram above were all made this way.
          </p>
        </div>
        <table>
          <thead>
            <tr><th /><th>Syntax tree</th><th>Rebalanced</th></tr>
          </thead>
          <tbody>
            {rows.map(([name, before, after]) => (
              <tr key={name}><th>{name}</th><td>{before}</td><td className="after">{after}</td></tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="facts">
        <div className="numbers">
          <div><b>{m.statementCount}</b><span>statements on this one run</span></div>
          <div><b>{m.chartedFunctions}</b><span>functions with their own chart</span></div>
          <div><b>{m.groups}</b><span>named groups made by the rebalancing pass</span></div>
          <div><b>{fns}</b><span>functions indexed across {m.repoCounts.module} modules</span></div>
        </div>
        <div className="cols">
          <div>
            <h3>From the 2023 prototype</h3>
            <ul>
              <li>The call graph, the flowchart of each function on this run's path, and the links from call sites into callees.</li>
              <li>The label on every statement and the summary of every function, written by a language model.</li>
              <li>A hierarchy of question-answering agents over the same index. They are not running on this page.</li>
            </ul>
          </div>
          <div>
            <h3>Added since</h3>
            <ul>
              <li>The rebalancing pass, its named groups, and the comparison of grouping methods behind it.</li>
              <li>This viewer, with code snippets re-attached to nodes from the cached source.</li>
              <li>Pre-computed answers, so the page needs no model and no key.</li>
            </ul>
          </div>
        </div>
      </section>

      <section className="cta">
        <div>
          <h2>Read the story behind it</h2>
          <p>A write-up of the project: the problem it went after, how the pipeline works, and the code on GitHub.</p>
        </div>
        <div className="cta-links">
          <a className="primary" href={LINKS.writeup} target="_blank" rel="noreferrer">Read the write-up</a>
          <a href={LINKS.repo} target="_blank" rel="noreferrer">Source on GitHub</a>
        </div>
      </section>

      <footer>
        <span>Codezoom · a research prototype by Jun Jiang, started in 2023</span>
        <span>Demo data: Auto-GPT {m.version}, MIT-licensed. Code excerpts belong to its contributors.</span>
      </footer>
    </div>
  );
}
