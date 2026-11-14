# Merging low-level logic into high-level blocks

How Codezoom turns the flowchart the 2023 pipeline produces into a hierarchy worth
zooming through, what was tried, and what the numbers say.

## The problem

The 2023 pipeline gives one node per statement, nested the way the syntax nests, with
each callee's chart inlined at its call site. For Auto-GPT's `run_auto_gpt` that is 772
nodes. As a hierarchy it has two faults:

- **Too thin.** 158 of its 268 charts have one or two steps: `x = f()` is a wrapper
  around a call and a "store the result" step; a one-armed `if` is a test and a body.
  The deepest statement is 21 levels down, the average one 8.
- **Too wide where it matters.** The entry function shows 21 steps at once, four other
  functions 13.

Neither says what the program does. The top level of the first demo was grouped by hand.

## The approach

`codezoom/retree.py` keeps every statement and every control-flow edge and changes only
how they are bundled. It uses two operations:

- **expand** a step: replace it with the chart inside it;
- **group** a run of steps: bundle them into one new, named step.

Starting at the root, for each chart:

1. If the chart holds at most 10 statements, expand everything. The last level is then a
   real statement-level flowchart with its branches and loops.
2. Otherwise expand while the chart has fewer than 3 steps, or while one step holds more
   than 60% of its statements. This is what removes wrapper levels and steps "through"
   a call or a loop that is the whole point of its parent.
3. If more than 7 steps remain (8 at the top), group them.
4. Recurse into every step that still has a chart.

A group must be **consecutive** in execution order and have **one way in and one way
out**, so that it can be drawn as a single box with one arrow in and one out. A loop test
alone has two exits and cannot be merged with the steps before it; a test together with
the whole loop body can.

Before all this, `x = f()` wrappers are folded: the wrapper becomes the call.

### Which steps go together

Two ways to choose the groups, both behind the same validity check:

- **A language model** reads the steps (label, statement count, first code lines) and
  returns consecutive groups with a title and a one-sentence summary each. Answers are
  cached in `codezoom/cache/groupings.json`, keyed by the chart's steps, so a build is
  deterministic and needs no key.
- **A segmenter** (`segment.min_cut_dp`), used when no model answer is cached or the
  model's groups break the one-way-in, one-way-out rule. It builds an affinity matrix
  from three signals and picks the cuts that sever the least affinity while keeping
  statement counts even, by dynamic programming:
  - *flow*: the steps are joined by an edge;
  - *data*: one writes a name the other reads, rare names counting more;
  - *lexical*: TF-IDF cosine of labels and identifiers.

  Groups the segmenter makes are still named by the model.

## What was tried

Reference groupings for the 11 widest charts were written by hand
(`codezoom/gold/segments.json`, 43 boundaries). `python3 -m codezoom.evaluate` scores
each approach by exact boundary precision, recall and F1, and by WindowDiff (lower is
better, near misses cost less).

With the number of groups left to each method:

| Approach | P | R | F1 | WindowDiff |
| --- | --- | --- | --- | --- |
| Uniform length | 0.44 | 0.40 | 0.41 | 0.40 |
| Equal statement count | 0.58 | 0.42 | 0.49 | 0.50 |
| Louvain on the affinity graph (the 2023 approach) | 0.60 | 0.35 | 0.44 | 0.51 |
| Modularity, contiguous, exact DP: flow only | 0.57 | 0.30 | 0.39 | 0.48 |
| Modularity DP: flow + data | 0.52 | 0.30 | 0.38 | 0.53 |
| Modularity DP: flow + lexical | 0.67 | 0.33 | 0.44 | 0.48 |
| Modularity DP: all three signals | 0.65 | 0.35 | 0.45 | 0.46 |
| Modularity DP: all three, resolution 1.5 | 0.60 | 0.42 | 0.49 | 0.43 |
| **Min-cut + balance DP, all three signals** | 0.67 | 0.60 | **0.63** | 0.42 |
| **Language model** | 0.78 | 0.81 | **0.80** | 0.20 |

What this shows:

- **Modularity under-segments.** Whether solved greedily (Louvain) or exactly under a
  contiguity constraint, it finds a third of the reference boundaries. A flowchart is
  close to a path, and modularity on a path favours a few long groups. Raising the
  resolution helps a little.
- **Lexical similarity carries most of the signal.** Adding def-use data flow on its own
  does not help: hub names such as `config` tie everything to everything, even with rare
  names weighted up.
- **Cutting where affinity is lowest, with a balance term, is the best method without a
  model.** Given the reference number of groups it reaches F1 0.67.
- **The model is clearly better** and also supplies the names, which no structural
  method can. It is therefore the first choice, with the segmenter as the fallback and
  the validity check as the guard on both.

Caveats: 11 charts from one program is a small sample; the references and the model's
answers both come from language models' reading of the code, by way of the person who
wrote the references with one, so the model's score is likely flattered; nothing was
tuned on a held-out set.

## The top level is balanced by weight

Grouping by meaning alone gave an overview that followed the order of the code: seven of
eight top-level steps were start-up, and the agent loop, 170 of the 439 statements, was
one box (`run_interaction_loop()`).

The top level now has one extra rule (`Config.root_share`, 0.3): no step there may hold
more than that share of the program's statements. A heavier step is expanded into the
top level, and no group made there may exceed the cap; the cap is given to the model in
its request and enforced by the same validity check as the single-entry, single-exit
rule. For Auto-GPT this opens the loop: the top level becomes four start-up steps, the
`while` test, and the loop's three phases (think, show and confirm, execute), with the
loop's back edge drawn at the top level.

The rule is a proxy. Statement count stands in for importance, which holds here and will
not hold everywhere (a long argument parser is heavy and dull).

## What it does to the tree

`python3 -m codezoom.export` prints these for Auto-GPT's `run_auto_gpt`:

| | 2023 tree | Rebalanced |
| --- | --- | --- |
| Deepest statement (levels) | 21 | 6 |
| Average statement depth | 8.1 | 4.3 |
| Charts with 3 to 8 steps | 39% | 76% |
| Charts with 1 or 2 steps | 158 | 18 |
| Widest chart | 21 | 10 |

For this build the model's grouping was used for 15 charts and the segmenter's for 4,
where the model's answer broke the validity rule; all 59 groups carry model-written names.

The remaining wide charts are statement-level charts under the 10-statement budget. The
remaining two-step charts are mostly a test and one action with nothing left to expand.

`tests/test_codezoom.py` checks that rebalancing is lossless (same statements before
and after), deterministic, leaves no edge pointing at a removed step, and respects the
validity rule.

## Known weaknesses

- **Function boundaries blur.** When a call holds most of a chart it is expanded in
  place, so the caller's and callee's steps share one chart. The site shows which
  functions a chart runs inside, but the function is no longer a box of its own.
- **Thresholds are judgment calls** (3, 7, 60%, 10 statements), chosen by looking at
  this one program.
- **A model answer that fails the validity check is dropped whole** in favour of the
  segmenter, instead of being repaired.
- **Labels of 2023 nodes are untouched**, including the loose ones.

## Ideas not yet tried

- Repair an invalid model grouping by moving a boundary to the nearest valid place.
- Let the model see the segmenter's affinity cuts as hints, or score candidate
  segmentations instead of proposing one.
- Cross-function groups at the top level driven by the call graph's module structure.
- A second program, to see which thresholds survive.
