# Development goal: Ichigen Coder showroom demo

Status: open · Owner: Jun Jiang · Written 2026-11-13

## Why we are doing this

Ichigen Coder (2023) is an early repo-understanding tool. It turns a Python codebase into a **hierarchical flowchart**: the top level shows what the program does, and every node can be zoomed into until you reach statement-level logic taken from the Python syntax tree. A hierarchy of agents (repo → package → module → function) answers questions about the code. In 2023 it answered questions about large Python repos better than GitHub Copilot Chat.

Today the work is invisible. The README says the project is "at very initial stage," there are no screenshots, and running it needs a 2023 toolchain. Jun is applying to AI coding-tool roles; Amazon Kiro's job posting asks for "representations of code that fuse static analysis, symbol and call graphs, type information… at repository scale." This repo did that in 2023. We want a **public demo website** that shows the idea in 30 seconds to a hiring manager, hosted on Jun's own domain (junbot.dev).

This is a **showroom project**: it needs to look and feel good and tell the story, not be a general product.

## What already exists (read before building)

Pipeline for one entry point of a CLI program:
1. **Call graph:** PyCG (`third_party/PyCG`, dependency `pycg`) builds the call graph of the repo starting from the entry point. Output is FASTEN JSON (`*_fasten.json`).
2. **Code info:** `codebase_analyzer/parser/` (`callgraph.py`, `deftree.py`, `codeinfo.py`) merges the call graph with the definition tree (package → module → class → function) into `codeinfo.json`.
3. **Flowchart:** `codebase_analyzer/flowchart/` walks the Python syntax tree of each function and converts it into flowchart nodes (`StartNode`, `ActionNode`, `CallNode`, `DecisionNode`, `EndNode`). An LLM writes a plain-English label for each node (`label.py`, `process/generate.py`). `CallNode`s carry `func_uri`, which links to the callee's own flowchart. That link is what makes zooming in possible.
4. **Grouping:** `customized_louvain.py` / `group.py` cluster related nodes (community detection) so a long function collapses into a few higher-level steps.
5. **Bots:** `codebase_analyzer/bots/` are the question-answering agents, one per level.

Data we can use right away (Auto-GPT v0.4.7, entry point `autogpt/app/cli.py` → `run_auto_gpt`):
- `convert_dump/linked_element.json`: **Cytoscape.js elements format** with 774 nodes (compound nodes via `parent`) and 667 edges, with an LLM label on each node.
- `convert_dump/linked_flat.json`: the same graph as a linked list (`start`, `nodes{uuid: {label, type, next, parent_uuid, expand, code...}}`).
- `shared_cache/Auto-GPT/`: `codeinfo.json`, `cli_fasten.json`, `overview.csv`, plus package- and module-level SVGs made with Graphviz.

Some of this is unfinished (the community-detection work stopped in January 2024, and there are uncommitted changes in `flowchart/group.py` and `tools/embedding.py`). Treat the data files as the source of truth for the demo, and fix or regenerate only what the demo needs.

## What to build

A static-first website under `demo/` that shows one repo (Auto-GPT v0.4.7, `run_auto_gpt`), understood automatically.

### 1. Hierarchical flowchart with semantic zoom
- **Level 0, "What this program does":** 5–9 big steps summarizing the whole run. Example: load config → set up logging → choose AI profile → build agent → interaction loop.
- **Middle levels:** each step opens into its sub-steps (community groups, then functions).
- **Lowest level:** the statement-level flowchart of one function (decisions, calls, actions), with the source lines next to it.
- **Two ways to zoom:** click a node to open it, or scroll / pinch to zoom in and out. Show a breadcrumb trail (e.g. `Program › Build agent › create_config()`), and give a way back up.
- A `CallNode` that points to another function opens that function's flowchart.

### 2. Motion that makes it feel alive
- Smooth animated transitions when entering or leaving a level: the clicked node expands into its child graph, and its children fade and scale in.
- Animated layout changes, hover highlights, and highlighting of the execution path along edges.
- Pick whatever library fits, e.g. React Flow or Cytoscape.js for the graph, Framer Motion for transitions, and ELK or dagre for layout. Polish matters more than generality.

### 3. Ask about any node
- Clicking a node opens a **floating panel next to it** with:
  - its label and code snippet;
  - a short summary;
  - a question box with 2–3 suggested questions.
- The answer is grounded in that node's context: its code, its parents and its callees.
- **The agent can drive the diagram.** When an answer refers to another part of the code, the agent calls UI tools such as `focus_node(id)`, `zoom_to_level(id)` and `highlight_path([ids])`, so the view animates to that place. Example: "Where does the user's input get handled?" → the view zooms to the interaction loop and highlights the path.
- There is also a general chat entry point (a side panel or the bottom of the page) for whole-program questions.

### 4. Works without a key
- Ship **pre-computed answers** for the suggested questions, so the demo works with no LLM key and costs nothing to host.
- The optional live mode uses a small server endpoint, for example a serverless function. The model key is read from an environment variable and never sent to the browser.

### 5. Story around it
- A short landing section:
  - what the project is (a 2023 research prototype);
  - the pipeline in one diagram (call graph → syntax-tree flowcharts → LLM labels → clustering → agents);
  - a link to the write-up at `https://www.junbot.dev/article/repo-understanding-tool`.
- Rewrite the repo `README.md` to include:
  - a pitch;
  - a GIF or screenshot of the demo;
  - an architecture section;
  - a "status: 2023 research prototype; demo at …" line;
  - working instructions for running the demo.
  - Remove or fix the setup steps that no longer work.

## Scope

**In scope:**
- one target repo and one entry point, Auto-GPT `run_auto_gpt`;
- Python only;
- hard-coded data, labels, Level-0 groupings and canned answers where that is faster;
- a desktop-first layout that still looks fine on a phone.

**Not in scope:**
- analyzing arbitrary repos or more than one entry point;
- other languages;
- user uploads;
- accounts;
- making the old Python CLI work again, unless that's the easiest way to regenerate data.

## Constraints
- **No secrets in git.** An old OpenAI key was committed in April 2023 (commit `367d40d`) and has been revoked. Don't add keys anywhere. Make sure `.env` and `config.yaml` are git-ignored before committing.
- Don't rewrite git history or force-push. Work on a branch, e.g. `demo-site`, and open a PR.
- Put new code in `demo/`, and keep changes to `codebase_analyzer/` small: only export scripts that turn existing data into the demo's JSON.
- Don't name employers or products other than Auto-GPT and Copilot. Don't write "outperformed Copilot Chat" on the site unless Jun supplies the comparison. Use it only as a claim Jun approves.
- The build output must be static, so it can be hosted on junbot.dev (a subpath or subdomain). Document the deploy steps.

## Definition of done
- [ ] `demo/` builds with one command and runs locally with one command; both are written in `demo/README.md`.
- [ ] Level-0 overview → at least 2 levels of zoom → a statement-level flowchart with code, all from the Auto-GPT data.
- [ ] Animated zoom in and out, both by click and by scroll; the breadcrumb works; back navigation works.
- [ ] Click any node → a floating panel with label, code and an ask box; the suggested questions return answers without a key.
- [ ] At least 3 canned answers move the diagram: focus, zoom or highlight a path.
- [ ] Optional live-LLM mode behind an environment variable, with the key kept on the server.
- [ ] A landing section with the pipeline diagram and the write-up link.
- [ ] The repo README is rewritten with a demo GIF or screenshot and a live link placeholder.
- [ ] No secrets in the diff; a static build works for hosting on junbot.dev.
- [ ] A short `demo/NOTES.md`: what is generated versus hard-coded, and how to regenerate the data.

## Open questions for Jun (decide sensibly if no answer)
- Hosting path: `junbot.dev/ichigen` or `ichigen.junbot.dev`.
- Which model for live mode.
- Whether the Copilot Chat comparison can be shown (needs the original questions and answers).
