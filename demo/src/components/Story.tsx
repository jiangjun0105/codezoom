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
    name: "Clustering",
    text: "Community detection over the graph, weighted by label embeddings, to fold long functions into a few higher-level steps. Experimental: the levels above come from code nesting and call links.",
    file: "flowchart/customized_louvain.py",
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
  const m = graph.meta as typeof graph.meta & { depth: number; repoCounts: Record<string, number> };
  const fns = m.repoCounts.function + m.repoCounts.class_method;
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

      <section className="facts">
        <div className="numbers">
          <div><b>{m.nodeCount}</b><span>flowchart nodes on this one run</span></div>
          <div><b>{m.chartedFunctions}</b><span>functions with their own chart</span></div>
          <div><b>{m.depth}</b><span>levels from overview to deepest statement</span></div>
          <div><b>{fns}</b><span>functions indexed across {m.repoCounts.module} modules</span></div>
        </div>
        <div className="cols">
          <div>
            <h3>What the 2023 pipeline produced</h3>
            <ul>
              <li>The call graph, the nested flowchart of each function on this run's path, and the links from call sites into callees.</li>
              <li>The label on every node and the summary of every function, written by a language model.</li>
              <li>A hierarchy of question-answering agents over the same index. They are not running on this page.</li>
            </ul>
          </div>
          <div>
            <h3>What was added for this demo</h3>
            <ul>
              <li>This viewer, and the eight hand-grouped steps at the top level.</li>
              <li>Code snippets re-attached to nodes from the cached source.</li>
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
        <span>Ichigen Coder · a 2023 research prototype by Jun Jiang</span>
        <span>Demo data: Auto-GPT {m.version}, MIT-licensed. Code excerpts belong to its contributors.</span>
      </footer>
    </div>
  );
}
