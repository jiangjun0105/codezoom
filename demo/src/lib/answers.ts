import { PROGRAM_QUESTIONS } from "../data/authored";
import type { Action } from "../store";
import {
  ROOT,
  callSites,
  canEnter,
  crumbs,
  displayOf,
  enterTarget,
  flowOrder,
  fnInfo,
  graph,
  leafCount,
  modulePath,
  node,
  shortFn,
} from "./graph";

export interface Answer {
  text: string;
  actions: Action[];
  /** authored = written by hand for the demo; derived = assembled from the 2023 labels, summaries and call graph */
  source: "authored" | "derived";
}
export interface Suggestion {
  q: string;
  answer: () => Answer;
}

const ref = (id: string, text?: string) => `[[${id}|${text ?? node(id).title}]]`;
const lower = (s: string) => (s ? s[0].toLowerCase() + s.slice(1) : s);
const trimDot = (s: string) => s.replace(/[.\s]+$/, "");

/** First sentences of the 2023 function-agent summary, up to a length budget. */
function brief(summary: string, budget = 380): string {
  const flat = summary.replace(/\s+/g, " ").trim();
  const parts = flat.match(/[^.!?]+[.!?]+(\s|$)/g) ?? [flat];
  let out = "";
  for (const p of parts) {
    if (out && out.length + p.length > budget) break;
    out += p;
  }
  return out.trim();
}

function inside(id: string): Suggestion {
  const n = node(id);
  const target = enterTarget(id)!;
  const callee = node(target).type === "call" ? node(target).callee : undefined;
  const q =
    n.kind === "group"
      ? `What happens in “${n.title}”?`
      : callee
        ? `What does ${shortFn(callee)}() do?`
        : n.kind === "for_wrapper" || n.kind === "while_wrapper"
          ? "What happens inside this loop?"
          : n.kind === "if_wrapper"
            ? "What happens inside this branch?"
            : "What happens inside this block?";
  return {
    q,
    answer: () => {
      const steps = flowOrder(target).filter((c) => node(c).type !== "start" && node(c).type !== "end");
      const info = callee ? fnInfo(callee) : undefined;
      const count = `${steps.length} step${steps.length === 1 ? "" : "s"} at this level, ${leafCount(target)} statements underneath`;
      let text = info?.summary
        ? `${brief(info.summary)}\n\nIts chart has ${count}:\n`
        : n.kind === "group"
          ? `${n.label}\n\nIt has ${count}:\n`
          : `It has ${count}:\n`;
      text += steps
        .slice(0, 6)
        .map((c) => `- ${ref(c, trimDot(node(c).label))}`)
        .join("\n");
      if (steps.length > 6) text += `\n- and ${steps.length - 6} more.`;
      return { text, actions: [{ tool: "zoom_to_level", id: target }], source: "derived" };
    },
  };
}

function leafCall(id: string): Suggestion {
  const n = node(id);
  const name = shortFn(n.callee!);
  return {
    q: `What does ${name}() do?`,
    answer: () => {
      const info = fnInfo(n.callee!);
      const sites = callSites(n.callee!);
      let text = info?.summary ? brief(info.summary) : `${n.label} No summary was generated for this function.`;
      if (!info?.code) text += "\n\nIt has no chart of its own because it lies outside the analysed call graph.";
      else if (sites.length > 1)
        text += `\n\nIt is called from ${sites.length} places in this run (now highlighted). The linker keeps functions like that as single nodes instead of repeating their chart at every call site.`;
      else text += "\n\nNo flowchart was generated for it in this run, so it stays a single node.";
      return {
        text,
        actions: sites.length > 1 ? [{ tool: "highlight_path", ids: sites }] : [],
        source: "derived",
      };
    },
  };
}

function callers(id: string): Suggestion {
  const n = node(id);
  const name = shortFn(n.callee!);
  return {
    q: `Who calls ${name}()?`,
    answer: () => {
      const info = fnInfo(n.callee!);
      const by = info?.calledBy ?? [];
      const sites = callSites(n.callee!);
      let text = by.length
        ? `The call graph lists ${by.length} caller${by.length === 1 ? "" : "s"} across the repository:\n` +
          by.slice(0, 6).map((u) => `- \`${shortFn(u)}\` in \`${modulePath(u)}\``).join("\n") +
          (by.length > 6 ? `\n- and ${by.length - 6} more.` : "")
        : "The call graph has no recorded callers for it.";
      text += `\n\nOn the path from \`run_auto_gpt\` it is reached ${sites.length === 1 ? "once, here" : `${sites.length} times; the call sites are highlighted`}.`;
      return { text, actions: [{ tool: "highlight_path", ids: sites }], source: "derived" };
    },
  };
}

function branches(id: string): Suggestion {
  const n = node(id);
  return {
    q: "What happens on each branch?",
    answer: () => {
      const loop = n.kind === "for_check";
      const yes = n.yes ? `${ref(n.yes, trimDot(lower(node(n.yes).label)))}.` : "nothing here; execution continues after this block.";
      const no = n.no ? `${ref(n.no, trimDot(lower(node(n.no).label)))}.` : loop ? "the loop ends and execution continues after it." : "nothing here; execution continues after this block.";
      const text = `The test is \`${(n.code ?? n.title).replace(/^if |:$/g, "")}\`.\n- **Yes:** ${yes}\n- **No:** ${no}`;
      return {
        text,
        actions: [{ tool: "highlight_path", ids: [id, n.yes, n.no].filter(Boolean) as string[] }],
        source: "derived",
      };
    },
  };
}

function next(id: string): Suggestion {
  const n = node(id);
  return {
    q: "What happens next?",
    answer: () => {
      if (n.next) {
        return {
          text: `After this, ${ref(n.next, trimDot(lower(node(n.next).label)))}.`,
          actions: [{ tool: "highlight_path", ids: [id, n.next] }],
          source: "derived",
        };
      }
      const { scope } = displayOf(id);
      return {
        text: `This is the last step of ${ref(scope)}. Control goes back to the level above and continues after that block.`,
        actions: [],
        source: "derived",
      };
    },
  };
}

function where(id: string): Suggestion {
  return {
    q: "How does execution get here?",
    answer: () => {
      const { scope } = displayOf(id);
      const trail = crumbs(scope).filter((c) => c.id !== ROOT);
      const text =
        "Following the highlighted step down from the top level:\n" +
        trail.map((c) => `- ${ref(c.id, c.title)}: ${lower(trimDot(node(c.id).label))}`).join("\n") +
        `\n- ${ref(id, "this node")}, ${trail.length + 1} level${trail.length ? "s" : ""} below the program overview.`;
      return {
        text,
        actions: [
          { tool: "zoom_to_level", id: ROOT },
          { tool: "highlight_path", ids: [id] },
        ],
        source: "derived",
      };
    },
  };
}

/** Suggested questions for a node. Every answer is computed from data shipped with the page. */
export function suggestionsFor(id: string): Suggestion[] {
  const n = node(id);
  const out: Suggestion[] = [];
  if (canEnter(id)) out.push(inside(id));
  else if (n.type === "call") out.push(leafCall(id));
  else if (n.type === "decision") out.push(branches(id));
  else out.push(next(id));
  if (n.type === "call") out.push(callers(id));
  if (n.parent !== ROOT) out.push(where(id));
  else out.push(next(id));
  return out;
}

export const programSuggestions: Suggestion[] = PROGRAM_QUESTIONS.map((a) => ({
  q: a.q,
  answer: () => ({ text: a.text, actions: a.actions, source: "authored" as const }),
}));

const STOP = new Set("a an the is are was does do did what where when which who how why in on at of to for from this that it its get gets got here there and or be with by about into me tell show can you i".split(" "));
const words = (s: string) =>
  s.toLowerCase().replace(/[^a-z0-9_ ]+/g, " ").split(/\s+/).filter((w) => w.length > 1 && !STOP.has(w)).map((w) => w.replace(/(ing|ed|es|s)$/, ""));

/** Without a model, a typed question is matched to the closest pre-computed one. */
export function matchQuestion(question: string, nodeId: string | null): Suggestion | null {
  const qw = new Set(words(question));
  if (!qw.size) return null;
  const pool = [...(nodeId ? suggestionsFor(nodeId) : []), ...programSuggestions];
  let best: Suggestion | null = null, bestScore = 0;
  for (const s of pool) {
    const sw = words(s.q);
    const hit = sw.filter((w) => qw.has(w)).length;
    const score = hit / Math.max(2, Math.min(sw.length, qw.size));
    if (hit >= 1 && score > bestScore) {
      best = s;
      bestScore = score;
    }
  }
  return bestScore >= 0.5 ? best : null;
}

export const stats = {
  nodes: graph.meta.nodeCount,
  functions: graph.meta.functionCount,
  charted: graph.meta.chartedFunctions,
};
