/**
 * Optional live mode: POST /api/ask answers a typed question with a model.
 *
 * Runs as a Vercel Function (and inside `npm run dev` through vite.config.ts). The key
 * stays here, in ANTHROPIC_API_KEY; the browser only ever sees the answer. The static
 * site works without this file: when the endpoint is missing or switched off, the page
 * falls back to its pre-computed answers.
 *
 * Environment:
 *   ANTHROPIC_API_KEY   required for live mode
 *   ICHIGEN_LIVE=1      required; lets you deploy the key without opening the endpoint
 *   ICHIGEN_MODEL       optional, default claude-haiku-5-5
 *   ICHIGEN_DAILY_CAP   optional, max requests per day per instance, default 400
 */
import Anthropic from "@anthropic-ai/sdk";
import graph from "../src/data/graph.json" with { type: "json" };

interface GNode {
  id: string;
  type: string;
  kind: string;
  label: string;
  title: string;
  parent: string | null;
  children: string[];
  callee?: string;
  fn: string;
  lines?: number[];
  code?: string;
  next?: string;
  yes?: string;
  no?: string;
}
interface GFn {
  name: string;
  summary?: string;
  code?: string;
  calledBy?: string[];
}
const nodes = graph.nodes as unknown as Record<string, GNode>;
const functions = graph.functions as unknown as Record<string, GFn>;

const MODEL = process.env.ICHIGEN_MODEL || "claude-haiku-5-5";
const enabled = () => Boolean(process.env.ANTHROPIC_API_KEY) && process.env.ICHIGEN_LIVE === "1";

const TOOLS: Anthropic.Tool[] = [
  {
    name: "zoom_to_level",
    description: "Move the diagram so it shows the chart inside one node (a step, block, loop or call that has children). Use it to show the user where something happens.",
    strict: true,
    input_schema: { type: "object", properties: { id: { type: "string", description: "Node id, copied exactly from the context." } }, required: ["id"], additionalProperties: false },
  },
  {
    name: "focus_node",
    description: "Travel to the chart that draws one node, select it and centre it.",
    strict: true,
    input_schema: { type: "object", properties: { id: { type: "string", description: "Node id, copied exactly from the context." } }, required: ["id"], additionalProperties: false },
  },
  {
    name: "highlight_path",
    description: "Light up an execution path. Give the node ids in execution order. Nodes deeper than the current view light up the step that contains them.",
    strict: true,
    input_schema: { type: "object", properties: { ids: { type: "array", items: { type: "string" }, description: "Node ids in execution order." } }, required: ["ids"], additionalProperties: false },
  },
];

const lineage = (id: string): GNode[] => {
  const out: GNode[] = [];
  for (let cur: string | null = id; cur && nodes[cur]; cur = nodes[cur].parent) out.push(nodes[cur]);
  return out.reverse();
};
const line = (n: GNode) => `${n.id} | ${n.title} | ${n.label}`;

/** The stable part of the prompt: what the page is, and a map of every node worth zooming to. */
const OUTLINE = (() => {
  const depth = (n: GNode) => lineage(n.id).length - 1;
  const landmarks = Object.values(nodes).filter(
    (n) => n.kind === "stage" || (n.type === "call" && n.children.length > 0) || n.children.length >= 3,
  );
  const order: string[] = [];
  const walk = (id: string) => {
    order.push(id);
    nodes[id].children.forEach(walk);
  };
  walk(graph.meta.root);
  const keep = new Set(landmarks.map((n) => n.id));
  return order.filter((id) => keep.has(id)).map((id) => `${"  ".repeat(Math.min(depth(nodes[id]), 8))}${line(nodes[id])}`).join("\n");
})();

const SYSTEM = `You answer questions inside an interactive flowchart of a Python program. The program is ${graph.meta.repo} ${graph.meta.version}, traced from ${graph.meta.entry}. The flowchart was generated in 2023 by a research prototype called Ichigen Coder: a static call graph, each function's syntax tree turned into flowchart nodes, and a one-line label per node written by a language model. Nodes nest: the top level has eight steps, and a node with children opens into its own chart, down to single statements.

The person asking is looking at the diagram. Answer from the context you are given: node labels, code and function summaries. If the context does not contain the answer, say what is missing instead of guessing. Labels were machine-written and can be loose; when a label and the code disagree, trust the code.

When your answer is about a place in the program, move the diagram there with the tools before you write: zoom_to_level to open a chart, highlight_path to light up a sequence of steps, focus_node to select one node. Use ids exactly as they appear in the context. One to three tool calls is typical; none is fine for a question that is not about a location.

Then write the answer: two to five sentences, or a short list when the content is a sequence. Plain text with \`backticks\` for code and "- " for list items. To make a phrase clickable, write [[node id|phrase]].

Map of the program (indented by nesting; each line is: id | title | label):
${OUTLINE}`;

/** The part that changes per question: the node the user has open and what surrounds it. */
function contextFor(nodeId: string | null, scope: string | null): string {
  const parts: string[] = [];
  const view = scope && nodes[scope] ? nodes[scope] : null;
  if (view) {
    parts.push(`The diagram currently shows the chart of: ${line(view)}`);
    parts.push("Steps in that chart:\n" + view.children.map((c) => "- " + line(nodes[c])).join("\n"));
  }
  const n = nodeId && nodes[nodeId] ? nodes[nodeId] : null;
  if (n) {
    parts.push(`The user selected this node: ${line(n)}`);
    parts.push("Path from the top: " + lineage(n.id).map((a) => a.title).join(" › "));
    if (n.code) parts.push("Its code:\n```python\n" + n.code.slice(0, 6000) + "\n```");
    for (const [name, to] of [["next", n.next], ["on yes", n.yes], ["on no", n.no]] as const)
      if (to && nodes[to]) parts.push(`Goes ${name} to: ${line(nodes[to])}`);
    if (n.children.length) parts.push("Inside it:\n" + n.children.map((c) => "- " + line(nodes[c])).join("\n"));
    const callee = n.callee ? functions[n.callee] : undefined;
    if (callee) {
      parts.push(`It calls ${callee.name}. 2023 summary: ${callee.summary ?? "none"}`);
      if (callee.code) parts.push("Callee source:\n```python\n" + callee.code.slice(0, 6000) + "\n```");
      if (callee.calledBy?.length) parts.push("Callers in the call graph: " + callee.calledBy.join(", "));
    }
  }
  return parts.join("\n\n");
}

// Best-effort limits. They reset when the function instance is recycled; set a spend
// limit on the key as the real backstop.
const perIp = new Map<string, number[]>();
let day = "", today = 0;
function allowed(ip: string): boolean {
  const now = Date.now(), d = new Date().toISOString().slice(0, 10);
  if (d !== day) (day = d), (today = 0);
  if (++today > Number(process.env.ICHIGEN_DAILY_CAP || 400)) return false;
  const recent = (perIp.get(ip) ?? []).filter((t) => now - t < 10 * 60_000);
  recent.push(now);
  perIp.set(ip, recent);
  return recent.length <= 15;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

export function GET(): Response {
  return json({ live: enabled() });
}

export async function POST(request: Request): Promise<Response> {
  if (!enabled()) return json({ error: "live mode is off" }, 404);
  const ip = request.headers.get("x-forwarded-for")?.split(",")[0].trim() || "local";
  if (!allowed(ip)) return json({ error: "rate limited" }, 429);

  let body: { question?: unknown; nodeId?: unknown; scope?: unknown; history?: unknown };
  try {
    body = await request.json();
  } catch {
    return json({ error: "bad request" }, 400);
  }
  const question = typeof body.question === "string" ? body.question.trim().slice(0, 400) : "";
  if (!question) return json({ error: "empty question" }, 400);
  const nodeId = typeof body.nodeId === "string" ? body.nodeId : null;
  const scope = typeof body.scope === "string" ? body.scope : null;
  const history = Array.isArray(body.history) ? body.history.slice(-6) : [];

  const messages: Anthropic.MessageParam[] = [];
  for (const h of history as { role?: string; text?: string }[]) {
    if ((h.role === "user" || h.role === "agent") && typeof h.text === "string" && h.text.trim())
      messages.push({ role: h.role === "user" ? "user" : "assistant", content: h.text.slice(0, 2000) });
  }
  if (messages[0]?.role === "assistant") messages.shift();
  messages.push({ role: "user", content: `${contextFor(nodeId, scope)}\n\nQuestion: ${question}` });

  const client = new Anthropic();
  const actions: unknown[] = [];
  let text = "";
  try {
    // The tools only move the user's screen, so every call "succeeds"; loop until the model has written its answer.
    for (let turn = 0; turn < 4; turn++) {
      const response = await client.messages.create({
        model: MODEL,
        max_tokens: 4000,
        output_config: { effort: "low" },
        system: [{ type: "text", text: SYSTEM, cache_control: { type: "ephemeral" } }],
        tools: TOOLS,
        messages,
      });
      if (response.stop_reason === "refusal") return json({ error: "declined" }, 422);
      const results: Anthropic.ToolResultBlockParam[] = [];
      for (const block of response.content) {
        if (block.type === "text") text += block.text;
        else if (block.type === "tool_use") {
          const input = block.input as { id?: string; ids?: string[] };
          const ids = (input.ids ?? (input.id ? [input.id] : [])).filter((id) => typeof id === "string");
          const unknown = ids.filter((id) => !nodes[id]);
          if (!unknown.length && ids.length) actions.push(block.name === "highlight_path" ? { tool: block.name, ids } : { tool: block.name, id: ids[0] });
          results.push({
            type: "tool_result",
            tool_use_id: block.id,
            content: unknown.length ? `No node has the id ${unknown.join(", ")}. Copy ids exactly from the context.` : "Done. The diagram moved.",
            is_error: unknown.length > 0,
          });
        }
      }
      if (response.stop_reason !== "tool_use") break;
      messages.push({ role: "assistant", content: response.content }, { role: "user", content: results });
    }
  } catch (error) {
    if (error instanceof Anthropic.RateLimitError) return json({ error: "busy" }, 429);
    if (error instanceof Anthropic.AuthenticationError) return json({ error: "server key rejected" }, 502);
    if (error instanceof Anthropic.APIError) return json({ error: `model error ${error.status ?? ""}`.trim() }, 502);
    return json({ error: "model unreachable" }, 502);
  }
  if (!text.trim()) return json({ error: "empty answer" }, 502);
  return json({ text: text.trim(), actions: actions.slice(0, 6) });
}
