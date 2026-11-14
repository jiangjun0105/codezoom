"""Build the JSON the demo site loads.

    python3 -m codezoom.export                 # rebalanced tree, model groupings from the cache
    python3 -m codezoom.export --no-model      # segmenter only, no cached model answers
    python3 -m codezoom.export --syntactic     # the 2023 tree as it was, for comparison
    python3 -m codezoom.export --merge a.json  # add model answers to the cache, then build
    python3 -m codezoom.export --ask           # answer pending requests through the API, then build

Output: demo/src/data/graph.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from . import oracle as oracle_mod
from .graph import REPO, ROOT, FnSource, Tree, load, module_of, short_fn
from .retree import Config, retree, shape

OUT = REPO / "demo" / "src" / "data" / "graph.json"

# The one hand-written sentence in the data: what the whole program does.
PROGRAM_LABEL = (
    "Auto-GPT starts up, builds an autonomous agent from configuration, commands, memory and an AI profile, "
    "then runs it in a think → approve → execute loop."
)

SYSTEM = "system"
SYSTEM_LABEL = (
    "What runs when you start Auto-GPT from the command line: one agent, set up from "
    "your settings, that works towards your goals one command at a time."
)


def build(tree: Tree, before: dict, mode: str) -> dict:
    sources: dict[str, FnSource | None] = {}

    def source(fn: str) -> FnSource | None:
        if fn not in sources:
            info = tree.codeinfo.get(fn)
            sources[fn] = (
                FnSource(info["code"]) if info and info.get("code") else None
            )
        return sources[fn]

    # groups span their members: same function -> one line range and snippet
    def span(node_id: str):
        node = tree[node_id]
        if node.kind != "group":
            return (node.fn, node.lines) if node.lines else None
        parts = [span(k) for k in node.children]
        if any(p is None for p in parts) or len({p[0] for p in parts}) != 1:
            return None
        return parts[0][0], (
            min(p[1][0] for p in parts),
            max(p[1][1] for p in parts),
        )

    nodes = {}
    for node in tree.nodes.values():
        out = dict(
            id=node.id,
            type=node.type,
            kind=node.kind,
            label=node.label,
            title=node.title,
            parent=node.parent,
            children=tree.flow_order(node.id) if node.children else [],
            fn=node.fn,
        )
        if node.children:
            out["entry"] = node.entry
        for key in ("next", "yes", "no", "callee", "code"):
            if getattr(node, key):
                out[key] = getattr(node, key)
        if node.lines:
            out["lines"] = list(node.lines)
        if node.kind == "group":
            got = span(node.id)
            src = source(got[0]) if got else None
            if got and src:
                out["fn"], out["lines"] = got[0], list(got[1])
                out["code"] = src.line_text(*got[1])
            out["generated"] = True
            out["namedBy"] = node.named_by
        if node.guard:
            out["guard"] = node.guard
        if node.loop or (
            node.kind == "group"
            and any((tree[k].code or "").startswith("while ") for k in node.children)
        ):
            out["loop"] = True
        if node.via:
            out["via"] = list(dict.fromkeys(node.via))
        if node.label_repaired:
            out["labelRepaired"] = True
        nodes[node.id] = out
    nodes[ROOT].update(
        title="Auto-GPT",
        label=PROGRAM_LABEL,
        authored=True,
        pipelineSummary=tree.pipeline_summary,
        parent=SYSTEM,
    )
    # the first scene: the whole system as one box, before any of its flow
    nodes[SYSTEM] = dict(
        id=SYSTEM,
        type="action",
        kind="system",
        label=SYSTEM_LABEL,
        title="Overview",
        parent=None,
        children=[ROOT],
        entry=ROOT,
        fn=tree.entry_fn,
        authored=True,
    )

    def resolve(node_id: str) -> str | None:
        seen = set()
        while node_id in tree.aliases and node_id not in seen:
            seen.add(node_id)
            node_id = tree.aliases[node_id]
        return node_id if node_id in nodes else None

    aliases = {old: new for old in tree.aliases if (new := resolve(old))}

    # an expanded step no longer has a chart of its own: point at the smallest chart that holds all of it
    def pieces(node_id: str) -> list[str]:
        if node_id in tree.expanded:
            return [p for k in tree.expanded[node_id] for p in pieces(k)]
        got = resolve(node_id)
        return [got] if got else []

    covers = {}
    for old in tree.expanded:
        paths = [tree.lineage(p) for p in pieces(old)]
        if not paths:
            continue
        common = 0
        while (
            all(len(p) > common for p in paths)
            and len({p[common] for p in paths}) == 1
        ):
            common += 1
        holder = paths[0][common - 1]
        covers[old] = holder if tree[holder].children else tree[holder].parent
    # a call folded into its `x = f()` wrapper shares the wrapper's fate
    for old, new in tree.aliases.items():
        if old not in covers and new in covers:
            covers[old] = covers[new]

    wanted = {n["fn"] for n in nodes.values()} | {
        n["callee"] for n in nodes.values() if n.get("callee")
    }
    wanted |= set(tree.fn_charts)
    charted = defaultdict(list)
    for n in nodes.values():
        if n.get("callee") and n["children"]:
            charted[n["callee"]].append(n["id"])
    functions = {}
    for uri in sorted(wanted):
        info = tree.codeinfo.get(uri)
        entry = dict(uri=uri, name=short_fn(uri), module=module_of(uri))
        if info:
            entry.update(
                code=info.get("code") or "",
                fileLine=info.get("lineno"),
                summary=(info.get("summary") or "").strip(),
                calls=sorted(info.get("calls") or []),
                calledBy=sorted(info.get("called_by") or []),
            )
        chart = (
            charted[uri][0]
            if uri in charted
            else resolve(tree.fn_charts.get(uri, ""))
        )
        if chart:
            entry["chart"] = chart
        functions[uri] = entry
    functions[tree.entry_fn]["chart"] = ROOT

    repo_counts = Counter(
        info.get("type", "other") for info in tree.codeinfo.values()
    )
    groups = [n for n in tree.nodes.values() if n.kind == "group"]
    after = shape(tree)
    return dict(
        meta=dict(
            repo="Auto-GPT",
            version="v0.4.7",
            entry="autogpt/app/cli.py → run_auto_gpt",
            root=SYSTEM,
            main=ROOT,
            entryFn=tree.entry_fn,
            mode=mode,
            nodeCount=len(nodes),
            statementCount=after["statements"],
            functionCount=len(functions),
            chartedFunctions=sum(1 for f in functions.values() if f.get("chart")),
            depth=after["max_depth"],
            groups=len(groups),
            groupsNamedByModel=sum(g.named_by == "model" for g in groups),
            chartsGroupedByModel=sum(v == "model" for v in tree.grouped_by.values()),
            chartsGroupedBySegmenter=sum(
                v == "segmenter" for v in tree.grouped_by.values()
            ),
            shapeBefore=before,
            shapeAfter=after,
            repoCounts=dict(repo_counts),
        ),
        nodes=nodes,
        functions=functions,
        aliases=aliases,
        covers=covers,
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--no-model", action="store_true")
    ap.add_argument("--syntactic", action="store_true")
    ap.add_argument("--merge", type=Path)
    ap.add_argument("--ask", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if args.merge:
        print(
            f"merged {oracle_mod.merge(json.loads(args.merge.read_text()))} answers into the cache"
        )
    if args.ask:
        print(f"asked the API for {oracle_mod.ask_api()} charts")

    tree = load()
    before = shape(tree)
    mode = "syntactic"
    if not args.syntactic:
        orc = None if args.no_model else oracle_mod.Oracle()
        retree(tree, Config(), orc)
        mode = "segmenter" if args.no_model else "model+segmenter"
        if orc:
            orc.flush()
            print(
                f"model groupings used: {orc.hits}, pending: {len(orc.pending)} charts + {len(orc.pending_names)} names"
                + (
                    f" (see {oracle_mod.PENDING.name})"
                    if orc.pending or orc.pending_names
                    else ""
                )
            )
    data = build(tree, before, mode)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    m = data["meta"]
    print(f"wrote {args.out} ({args.out.stat().st_size // 1024} KB), mode: {mode}")
    print(
        f"  nodes {m['nodeCount']}, statements {m['statementCount']}, groups {m['groups']}, functions with a chart {m['chartedFunctions']}"
    )
    for key in (
        "max_depth",
        "mean_depth",
        "share_3_to_8",
        "charts_with_2_or_fewer",
        "widest",
    ):
        print(f"  {key:24s} {before[key]:6.2f} -> {m['shapeAfter'][key]:6.2f}")


if __name__ == "__main__":
    main()
