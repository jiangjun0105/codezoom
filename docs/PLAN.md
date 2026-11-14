# Codezoom plan

Working plan for taking the 2023 prototype to a demo worth showing. Updated as work lands.

## Where things stand

- **Done.** Static demo site (`demo/`): zoomable flowchart of Auto-GPT, ask panel on
  every node, answers that move the diagram, optional live mode. Merged in PR #20.
- **Done.** Abstraction pass (`codezoom/`): rebalances the 2023 tree by expanding thin
  levels and grouping long runs into named blocks. The top level is now generated, not
  hand-written. Approaches compared in [abstraction.md](abstraction.md).
- **Done.** Viewer rework after feedback: continuous zoom into the step under the cursor,
  and graph layout at every level.
- **Not done.** The data still starts from 2023 dumps of one program. Live mode has never run against a real key.

## Track 1: understanding (how low-level logic becomes high-level blocks)

1. ~~Compare grouping methods against hand-written references.~~
2. ~~Rebalance the whole tree; generate the top level.~~
3. Repair model groupings that fail the single-entry, single-exit check instead of
   discarding them.
4. Re-label the loosest 2023 node labels (some describe the wrong statement).
5. Group across functions at the top, using module structure from the call graph, and
   compare with the current statement-order grouping.
6. Run on a second program to find out which thresholds are specific to Auto-GPT.

## Track 2: pipeline (make the back end reproducible)

The 2023 pipeline needs a 2023 toolchain and cannot be re-run today, so every input is a
frozen dump.

1. Port the three stages the demo depends on into `codezoom/`, standard library first:
   syntax tree → flowchart nodes; call linking; labels through the same cached-oracle
   pattern the grouping step uses.
2. Replace PyCG with a small resolver for direct calls and methods on known classes, and
   measure what it misses against the cached PyCG call graph for Auto-GPT.
3. One command: repository + entry point → `graph.json`.
4. Use it on a second repository (Track 1, step 6).

## Track 3: front end

1. ~~Continuous, cursor-driven zoom: the inner chart appears inside the step as it grows.~~
2. ~~One left-to-right graph layout for every level; skip edges, loop edges, and a
   miniature of the inner chart on every card.~~
3. Surface branching at high levels as real edges (today a group hides it by
   construction): try groups with two exits, or lifting a dominant decision out of a group.
4. Design review against screenshots at three widths; fix what reads badly.
5. Show function boundaries inside a chart that spans several functions.
6. A minimap or outline for orientation at depth.
7. Keyboard navigation between steps.
8. Record the README GIF.
9. Tune the phone layout; test pinch on a touch device.
10. ~~Wheel zoom with inertia.~~ Still to tune on real hardware.
11. ~~Search box (`/` or Cmd-K) that jumps to any step, function or line.~~
12. ~~3D view (prototype): the current chart, the charts above it, and the charts inside
    its steps as stacked sheets.~~ Open: frame around the side panel, touch gestures,
    a smoother hand-over between the flat and 3D views.

### Content review, 2026-11-13 (feeds Track 1)

Read as a developer who wants to know how Auto-GPT works:

Done since: the top level is balanced by weight (the loop's phases are top-level steps),
every top-level step is named, the `while` test and the "Do nothing." label are repaired.
Still open: the rest of this list.
Also done: two layers above the processes (a one-box system level and a 2–3 phase main flow),
with a caption on every level saying what it shows. 3D view: next, show every layer, not two.

- The top level follows code order and volume: 7 of 8 steps are start-up, and the agent
  loop (170 of 439 statements, the part people come for) is one box at the far right.
  Try weighting by importance: fold start-up into two or three steps and give the loop's
  phases (think, parse, confirm, execute) their own top-level steps.
- Top-level names mix named blocks with raw function names (`create_config()`,
  `check_openai_api_key()`, which is five statements). Name every top-level step.
- Statement labels from 2023 mostly restate the code ("Verify that `result` is not
  empty"), and some are wrong (the `while` test is labelled as an `if`; one call is
  labelled "Do nothing."). Re-label, or hide labels that add nothing over the code.
- Coverage is one path: 38 of 820 functions. Commands, memory back ends and the model
  client are reached through a registry or dynamic dispatch, which the static call graph
  does not follow, so "Run the command" ends where the interesting part begins.
- No view of data: what `config`, `agent` and `memory` hold and where they change.

## Track 4: ship

1. Run live mode against a real key; fix what breaks.
2. Deploy to junbot.dev; replace the README placeholder.
3. Rename the GitHub repository to `codezoom` (owner's action).

## Order

Track 1 steps 3–4 and Track 3 step 1 next, because they change what a visitor sees.
Track 2 is the largest piece and unlocks Track 1 step 6. Track 4 last.
