import { ROOT, node } from "../lib/graph";
import type { Action } from "../store";

/**
 * Hand-written answers to the whole-program questions (2026, for the demo).
 * Node ids are the pipeline's own uuids: /module/function:line:col:AstType:kind.
 * `[[id|text]]` in an answer renders as a link that focuses that node.
 */
const M = "/autogpt.app.main/";
export const N = {
  loop: `${M}run_auto_gpt:41:4:Call:call`,
  loopBody: `${M}run_interaction_loop:31:8:Expr:nodes_wrapper`,
  cycleBudget: `${M}run_interaction_loop:13:4:Assign:wrapper`,
  spinner: `${M}run_interaction_loop:32:8:With:with_wrapper`,
  think: `${M}run_interaction_loop:33:65:Call:call`,
  updateUser: `${M}run_interaction_loop:34:8:Call:call`,
  feedbackIf: `${M}run_interaction_loop:35:8:If:if_wrapper`,
  getFeedback: `${M}run_interaction_loop:36:64:Call:call`,
  feedbackRead: `${M}get_user_feedback:16:4:While:while_wrapper`,
  countDown: `${M}run_interaction_loop:57:8:If:simple`,
  executeWrap: `${M}run_interaction_loop:59:8:Assign:wrapper`,
  execute: `${M}run_interaction_loop:59:17:Call:call`,
  executeCommand: "/autogpt.agents.agent/Agent.execute:12:25:Call:call",
  showResult: `${M}run_interaction_loop:60:8:If:if_wrapper`,
  constructPrompt: "/autogpt.agents.base/BaseAgent.think:11:27:Call:call",
  beforeThink: "/autogpt.agents.base/BaseAgent.think:12:13:Call:call",
  completion: "/autogpt.agents.base/BaseAgent.think:13:4:Assign:wrapper",
  onResponse: "/autogpt.agents.base/BaseAgent.think:15:11:Call:call",
  continuousFlag: "/autogpt.app.configurator/create_config:25:4:If:if_wrapper",
  legalWarning: `${M}run_auto_gpt:7:4:If:if_wrapper`,
  profile: `${M}run_auto_gpt:29:16:Call:call`,
  promptUser: `${M}construct_main_ai_config:24:4:If:if_wrapper`,
};

const top = () => node(ROOT).children;

export interface Authored {
  q: string;
  text: string;
  actions: Action[];
}

export const PROGRAM_QUESTIONS: Authored[] = [
  {
    q: "Where does the user's input get handled?",
    actions: [
      { tool: "zoom_to_level", id: N.loopBody },
      { tool: "highlight_path", ids: [N.spinner, N.updateUser, N.feedbackIf] },
      { tool: "focus_node", id: N.feedbackIf },
    ],
    text:
      "In the interaction loop, right after the agent has shown its plan. The highlighted path is one cycle: think, [[" + N.updateUser + "|print the thoughts]], then [[" + N.feedbackIf + "|`if cycles_remaining == 1`]].\n\n" +
      "That branch calls [[" + N.getFeedback + "|`get_user_feedback()`]], which [[" + N.feedbackRead + "|keeps reading the console]] until the input is valid:\n" +
      "- the authorise key runs the proposed command;\n" +
      "- `y -N` authorises the next N commands without asking;\n" +
      "- the exit key quits;\n" +
      "- anything else is sent back to the agent as `human_feedback`.\n\n" +
      "When more than one authorised cycle is left, the branch is skipped and no input is read.",
  },
  {
    q: "How does the agent decide what to do next?",
    actions: [
      { tool: "zoom_to_level", id: N.think },
      { tool: "highlight_path", ids: [N.constructPrompt, N.beforeThink, N.completion, N.onResponse] },
    ],
    text:
      "One call to `BaseAgent.think()` per cycle. Its steps are lit in the diagram:\n" +
      "- [[" + N.constructPrompt + "|`construct_prompt()`]] builds the system prompt and adds as much message history as fits in the token limit;\n" +
      "- [[" + N.beforeThink + "|`on_before_think()`]] lets enabled plugins add their planning output to the prompt, while it still fits the token limit;\n" +
      "- [[" + N.completion + "|`create_chat_completion()`]] sends it to the model, with the command list as function specs when that option is on;\n" +
      "- [[" + N.onResponse + "|`on_response()`]] parses the reply into a command name, its arguments and the agent's thoughts.\n\n" +
      "The decision itself is the model's. The code only shapes the prompt and validates the reply.",
  },
  {
    q: "What happens before the agent starts running?",
    get actions(): Action[] {
      return [
        { tool: "zoom_to_level", id: ROOT },
        { tool: "highlight_path", ids: top() },
      ];
    },
    get text() {
      const steps = top();
      return (
        `Everything before the last of the ${steps.length} top-level steps is setup, all of it inside \`run_auto_gpt()\`:\n` +
        steps.slice(0, -1).map((id) => `- [[${id}|${node(id).title}]]: ${node(id).label.replace(/\.$/, "").replace(/^./, (c) => c.toLowerCase())};`).join("\n") +
        `\n\nOnly then does [[${steps[steps.length - 1]}|${node(steps[steps.length - 1]).title.replace(/^./, (c) => c.toLowerCase())}]] begin.`
      );
    },
  },
  {
    q: "Where are commands actually executed?",
    actions: [
      { tool: "zoom_to_level", id: N.loopBody },
      { tool: "highlight_path", ids: [N.feedbackIf, N.countDown, N.executeWrap, N.showResult] },
      { tool: "focus_node", id: N.executeWrap },
    ],
    text:
      "At the end of each cycle, in [[" + N.executeWrap + "|`result = agent.execute(...)`]]. By then the user has approved the command (or continuous mode has), and the cycle counter has been [[" + N.countDown + "|decremented]].\n\n" +
      "[[" + N.execute + "|`Agent.execute()`]] has three paths: a command name starting with `error` is reported back, `human_feedback` is logged, and everything else goes through the plugins' `pre_command` hooks into [[" + N.executeCommand + "|`execute_command()`]], which looks the command up in the registry built during startup.\n\n" +
      "The result is added to the message history, so the next `think()` sees it.",
  },
  {
    q: "What does continuous mode change?",
    actions: [
      { tool: "zoom_to_level", id: ROOT },
      { tool: "highlight_path", ids: [N.continuousFlag, N.legalWarning, N.cycleBudget] },
    ],
    text:
      "Three places, which is why three steps light up at this level:\n" +
      "- [[" + N.continuousFlag + "|`create_config()`]] turns the `--continuous` flag into `config.continuous_mode` and stores the optional limit;\n" +
      "- [[" + N.legalWarning + "|`run_auto_gpt()`]] prints the legal warning when the mode is on;\n" +
      "- [[" + N.cycleBudget + "|`_get_cycle_budget()`]] in the loop sets how many commands may run without approval: the limit, or infinity when there is none.\n\n" +
      "With a budget above one, the loop skips the approval prompt until the budget is used up.",
  },
  {
    q: "How was this diagram made?",
    actions: [],
    text:
      "Automatically, by the 2023 pipeline, from the Auto-GPT v0.4.7 source:\n" +
      "- a static call graph from the entry point decides which functions are reachable;\n" +
      "- each function's syntax tree is walked into start, action, call, decision and end nodes;\n" +
      "- a language model writes the plain-English label on every node;\n" +
      "- nested blocks and call sites are linked, so a call node opens the callee's own chart.\n\n" +
      "The 2023 output is deep and thin, so a rebalancing pass regroups it for zooming: it folds wrapper levels away and bundles long runs of steps into named groups. The section below the diagram has the details.",
  },
];
