# Notes: what is generated, what is hand-written

## Produced by the 2023 pipeline (unchanged)

| What | Source file |
| --- | --- |
| The 774 flowchart nodes, their types and `next` / `true` / `false` links | `convert_dump/linked_flat.json` |
| The nesting of nodes (blocks, and callee charts inside call nodes) | `convert_dump/linked_element.json` |
| The label on every node (written by an LLM in 2023) | both files |
| Function source, function summaries, `calls` / `called_by` | `shared_cache/Auto-GPT/codeinfo.json` |

## Derived by `scripts/export_data.py`

- **Code and line range per node.** The dumps have `code: null`. Node ids encode
  `function:line:col:AstType:kind`, so the script re-parses each function's cached source
  and looks the node up. 778 of 782 nodes get a snippet. Line numbers are those of the
  cached source (`ast.unparse` output), not of the original file.
- **Entry node of each block**, short titles, and counts shown in the story section.
- **36 label repairs**, each flagged `labelRepaired` in the JSON:
  - 2 decisions whose label was an LLM error message ("The provided code snippet is incomplete…");
  - 2 `with` enter/exit labels and 32 loop fetch/test labels, where a string template
    had pasted one label inside another.

## Hand-written for the demo (2026)

- **Level 0.** The eight steps, their titles, one-line blurbs and descriptions are
  written by hand in `STAGES` in `export_data.py`. Each step is a line range of
  `run_auto_gpt`; the 21 top-level statements are assigned by line. The pipeline's own
  top level was a single node, "process of 21 nodes".
- **Six whole-program answers** in `src/data/authored.ts`, with the diagram moves each
  one makes. They were checked against the cached Auto-GPT source.
- **The viewer**, including two display rules that are not in the data: an `x = f()`
  wrapper opens straight into `f`'s chart, and long charts wrap into columns.

## Computed in the browser

Per-node answers ("What happens inside this loop?", "Who calls it?", "What happens on
each branch?", "How does execution get here?") are assembled in `src/lib/answers.ts`
from the labels, summaries and call graph above. No model is involved. The page labels
them "Pre-computed from the 2023 labels and call graph".

A typed question with no model attached is matched to the closest pre-computed question
by word overlap. If nothing is close, the page says so and offers suggestions.

## Not in the demo

- **Community detection** (`flowchart/customized_louvain.py`, `group.py`). The work
  stopped in January 2024 and its output is not in the dumps. The levels you zoom
  through come from code nesting and call links.
- **The 2023 agents** (`codebase_analyzer/bots/`). Live mode is a new, small function
  with three UI tools; it does not run the original repo → package → module → function
  agents.
- Only 38 functions have charts. A function called from more than one place was kept as
  a single node by the 2023 linker, and stays one here.

## Regenerating the data

```bash
python3 demo/scripts/export_data.py     # or: cd demo && npm run export-data
```

Python 3.9+ and the standard library are enough. To change the top level, edit `STAGES`
and re-run. Regenerating the three input files themselves means running the 2023
pipeline (PyCG, pygraphviz, an LLM for labels), which this demo does not require.

## Known rough edges

- Some 2023 labels are loose or wrong for their statement. They are shown as generated.
- Live mode was written against the API documentation and type-checked, but not run
  against a real key.
- Phone layout is usable, not tuned: the node panel becomes a bottom sheet and the side
  panel a drawer.
