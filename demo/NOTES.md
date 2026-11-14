# Notes: what is generated, what is hand-written

## From the 2023 pipeline (unchanged inputs)

| What | Source file |
| --- | --- |
| The 774 flowchart nodes, their types and `next` / `true` / `false` links | `convert_dump/linked_flat.json` |
| The nesting of nodes (blocks, and callee charts inside call nodes) | `convert_dump/linked_element.json` |
| The label on every statement (written by an LLM in 2023) | both files |
| Function source, function summaries, `calls` / `called_by` | `shared_cache/Auto-GPT/codeinfo.json` |

## Derived by `codezoom/` (Python, standard library)

- **Code and line range per node** (`graph.py`). The dumps have `code: null`. Node ids
  encode `function:line:col:AstType:kind`, so the loader re-parses each function's cached
  source and looks the node up. Line numbers are those of the cached source
  (`ast.unparse` output), not of the original file.
- **36 label repairs**, flagged `labelRepaired`: 2 decisions whose label was an LLM error
  message, 2 `with` enter/exit labels and 32 loop fetch/test labels where a string
  template had pasted one label inside another.
- **The hierarchy you zoom through** (`retree.py`). The 2023 nesting is rebalanced:
  `x = f()` wrappers are folded, thin or lopsided charts are expanded, and over-full
  charts are grouped into named blocks. Every statement and edge is kept. Method,
  experiments and numbers are in [../docs/abstraction.md](../docs/abstraction.md).
- **Aliases.** Ids of steps that were folded or expanded away map to where their content
  went, so references to 2023 ids still resolve.

## Written by a language model in 2026, cached in the repository

- **Which steps form a group, and each group's title and summary**
  (`codezoom/cache/groupings.json`). The prompts are in `codezoom/oracle.py`. The cached
  answers came from Claude Haiku 5.5, run through Claude Code sub-agents on the pending
  requests the exporter writes, not through the exporter's own API path (`--ask`), which
  has not been run against a real key.
- A proposed grouping is used only if every group has one way in and one way out;
  otherwise the dynamic-programming segmenter chooses the groups and the model only
  names them. `meta` in `graph.json` records how many charts went each way.

## Hand-written

- **One sentence**: the description of the whole program (`PROGRAM_LABEL` in
  `codezoom/export.py`).
- **Five whole-program answers** in `demo/src/data/authored.ts`, with the diagram moves
  each makes, checked against the cached Auto-GPT source. A sixth lists the top-level
  steps and is built from the data.
- **Reference groupings** for 11 charts (`codezoom/gold/segments.json`), used only to
  compare grouping methods.
- **The viewer.** Its display rules are not in the data: every chart is laid out left to
  right; zoom is continuous, with a step's inner chart drawn inside it as it grows; a
  step that runs only under a one-armed `if` gets a dotted "skip" edge around it; each
  card carries a miniature of the chart inside it.

## Computed in the browser

Per-node answers ("What happens inside this loop?", "Who calls it?", "What happens on
each branch?", "How does execution get here?") are assembled in `src/lib/answers.ts`
from the labels, summaries and call graph. No model is involved. The page labels them
"Pre-computed from the 2023 labels and call graph".

A typed question with no model attached is matched to the closest pre-computed question
by word overlap. If nothing is close, the page says so and offers suggestions.

## Not in the demo

- **The 2023 community detection** (`codebase_analyzer/flowchart/customized_louvain.py`).
  It is one of the baselines in `docs/abstraction.md`; the site uses the rebalancing pass.
- **The 2023 agents** (`codebase_analyzer/bots/`). Live mode is a new, small function
  with three UI tools.
- A function called from more than one place was kept as a single node by the 2023
  linker, and stays one here.

## Regenerating the data

```bash
python3 -m codezoom.export              # rebuild demo/src/data/graph.json from the dumps and the cache
python3 -m codezoom.export --no-model   # segmenter only, fallback names
python3 -m codezoom.export --syntactic  # the 2023 tree as it was
python3 -m codezoom.evaluate            # compare grouping methods against the references
python3 -m pytest tests                 # 12 tests
```

Python 3.10+; `networkx` only for the Louvain baseline in `evaluate`, `pytest` for the
tests. Changing a threshold in `retree.Config` changes which charts need grouping; new
requests are written to `codezoom/cache/pending.json` and fall back to the segmenter
until answered (`--ask`, or `--merge answers.json`).

Regenerating the three input files themselves means running the 2023 pipeline, which
needs its 2023 toolchain. Porting that is Track 2 in [../docs/PLAN.md](../docs/PLAN.md).

## Known rough edges

- Some 2023 statement labels are loose or wrong. They are shown as generated.
- When a call is expanded in place, caller and callee steps share one chart. The node
  panel names the functions a chart runs inside; the chart itself does not draw the
  boundary.
- Live mode was written against the API documentation and type-checked, but not run
  against a real key.
- Phone layout is usable, not tuned, and pinch-zoom was not tested on a touch device.
- The 3D view is a prototype: mouse only, and it does not make room for the side panel.
- Wheel inertia was tuned by automation, not on a real trackpad.
- Charts above statement level are mostly straight sequences, because a group is by
  construction one way in, one way out. Their branching shows in the miniatures and one
  level down, not as edges at that level.
