import { useSyncExternalStore } from "react";
import { getState, runAction, set, type Action } from "../store";
import { matchQuestion, programSuggestions, suggestionsFor, type Answer, type Suggestion } from "./answers";
import { hasNode, node } from "./graph";

export type ThreadName = "panel" | "dock";
export interface Msg {
  id: number;
  role: "user" | "agent";
  /** text revealed so far */
  text: string;
  about?: string;
  actions?: Action[];
  /** how many actions have finished */
  done?: number;
  status?: "thinking" | "acting" | "typing" | "done";
  source?: Answer["source"] | "live" | "none";
  offers?: string[];
}

const threads: Record<ThreadName, Msg[]> = { panel: [], dock: [] };
const subs = new Set<() => void>();
const emit = () => subs.forEach((s) => s());
let seq = 1;
const runs: Record<ThreadName, number> = { panel: 0, dock: 0 };

export function useThread(name: ThreadName): Msg[] {
  return useSyncExternalStore(
    (l) => (subs.add(l), () => subs.delete(l)),
    () => threads[name],
  );
}
export function clearThread(name: ThreadName) {
  runs[name]++;
  if (threads[name].length) {
    threads[name] = [];
    emit();
  }
}
function patch(name: ThreadName, id: number, p: Partial<Msg>) {
  threads[name] = threads[name].map((m) => (m.id === id ? { ...m, ...p } : m));
  emit();
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const API = `${import.meta.env.BASE_URL}api/ask`;

/** Live mode exists only when the optional server function is deployed and has a key. */
let live: Promise<boolean> | null = null;
export function liveAvailable(): Promise<boolean> {
  live ??= fetch(API)
    .then((r) => (r.ok ? r.json() : { live: false }))
    .then((j) => j.live === true)
    .catch(() => false);
  return live;
}
const liveSubs = new Set<() => void>();
let liveNow = false;
void liveAvailable().then((v) => {
  liveNow = v;
  liveSubs.forEach((s) => s());
});
export const useLive = () =>
  useSyncExternalStore(
    (l) => (liveSubs.add(l), () => liveSubs.delete(l)),
    () => liveNow,
  );

async function askLive(question: string, nodeId: string | null, history: Msg[]): Promise<Answer | null> {
  try {
    const res = await fetch(API, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        question,
        nodeId,
        scope: getState().scope,
        history: history.filter((m) => m.status === "done" || m.role === "user").slice(-6).map((m) => ({ role: m.role, text: m.text })),
      }),
    });
    if (!res.ok) return null;
    const j = await res.json();
    const actions = (j.actions as Action[]).filter((a) =>
      a.tool === "highlight_path" ? a.ids.some(hasNode) : hasNode(a.id),
    );
    return { text: j.text, actions, source: "derived" };
  } catch {
    return null;
  }
}

/**
 * Ask a question. A suggested question always uses its pre-computed answer. A typed
 * one goes to the model in live mode, and otherwise to the closest pre-computed answer.
 */
export async function ask(name: ThreadName, question: string, nodeId: string | null, known?: Suggestion) {
  const q = question.trim();
  if (!q) return;
  const run = ++runs[name];
  const about = nodeId ? node(nodeId).title : undefined;
  const history = threads[name];
  const user: Msg = { id: seq++, role: "user", text: q, about };
  const reply: Msg = { id: seq++, role: "agent", text: "", status: "thinking" };
  threads[name] = [...threads[name], user, reply];
  emit();
  const alive = () => runs[name] === run;

  let answer: Answer | null = known ? known.answer() : null;
  let source: Msg["source"] = answer?.source;
  if (!answer && (await liveAvailable())) {
    answer = await askLive(q, nodeId, history);
    if (answer) source = "live";
  }
  if (!answer) {
    const hit = matchQuestion(q, nodeId);
    if (hit) {
      answer = hit.answer();
      source = answer.source;
    }
  }
  if (!alive()) return;
  if (!answer) {
    await sleep(350);
    if (!alive()) return;
    const pool = [...(nodeId ? suggestionsFor(nodeId) : []), ...programSuggestions];
    patch(name, reply.id, {
      status: "done",
      source: "none",
      text: "This page is running without a model, so it can only answer the questions it shipped with. These are close:",
      offers: pool.slice(0, 4).map((s) => s.q),
    });
    return;
  }

  await sleep(known ? 380 : 120);
  if (!alive()) return;
  const actions = answer.actions;
  patch(name, reply.id, { actions, done: 0, status: actions.length ? "acting" : "typing", source });
  if (actions.length) {
    set({ driving: true });
    try {
      for (let i = 0; i < actions.length; i++) {
        // answers in the side chat select a node without covering the chart with its panel
        await runAction(actions[i], name === "panel");
        if (!alive()) return;
        patch(name, reply.id, { done: i + 1 });
      }
    } finally {
      set({ driving: false });
    }
    patch(name, reply.id, { status: "typing" });
  }
  const full = answer.text;
  for (let i = 0; i < full.length; ) {
    // keep [[id|text]] links whole so a half-typed link never shows
    let j = Math.min(full.length, i + 5);
    const open = full.lastIndexOf("[[", j);
    if (open >= 0 && full.indexOf("]]", open) >= j) j = full.indexOf("]]", open) + 2;
    i = j;
    patch(name, reply.id, { text: full.slice(0, i) });
    await sleep(12);
    if (!alive()) return;
  }
  patch(name, reply.id, { status: "done", text: full });
}
