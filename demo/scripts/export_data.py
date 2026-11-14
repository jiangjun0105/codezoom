#!/usr/bin/env python3
"""Turn the 2023 pipeline dumps into the JSON the demo site loads.

Standard library only, so it runs without the 2023 toolchain:

    python3 demo/scripts/export_data.py

Inputs (all produced by the original pipeline, Auto-GPT v0.4.7):
    convert_dump/linked_flat.json      linked flowchart: labels, next/true/false links
    convert_dump/linked_element.json   same nodes, with the compound-node parent links
    shared_cache/Auto-GPT/codeinfo.json  call graph + definition tree + function source

Output:
    demo/src/data/graph.json

What this script adds on top of the dumps (see demo/NOTES.md):
    * the code snippet and line range of every node (the dumps have `code: null`),
      recovered by re-parsing the function source and matching `line:col:AstType`;
    * the hand-written Level-0 stages in STAGES below;
    * repairs for a handful of labels where the 2023 LLM call returned an error text
      or a string template leaked through.
"""
from __future__ import annotations

import ast
import json
import re
import textwrap
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FLAT = REPO / "convert_dump" / "linked_flat.json"
ELEMENT = REPO / "convert_dump" / "linked_element.json"
CODEINFO = REPO / "shared_cache" / "Auto-GPT" / "codeinfo.json"
OUT = REPO / "demo" / "src" / "data" / "graph.json"

ENTRY_FN = "/autogpt.app.main/run_auto_gpt"
ROOT_ID = "program"

# Hand-written Level 0. Each stage owns a range of (unparsed) source lines of
# run_auto_gpt; the top-level statements in that range become its children.
STAGES = [
    dict(
        id="stage:config",
        blurb="Environment variables, log level, API key check.",
        title="Load configuration",
        label="Set the log level, build the configuration from environment variables and check the OpenAI API key.",
        lines=(2, 5),
    ),
    dict(
        id="stage:options",
        blurb="Fold the CLI flags into the configuration.",
        title="Apply command-line options",
        label="Fold the CLI flags (continuous mode, speak, GPT-3.5/4 only, memory backend, browser, settings files) into the configuration.",
        lines=(6, 6),
    ),
    dict(
        id="stage:notices",
        blurb="Legal warning, news, git branch, Python version.",
        title="Show startup notices",
        label="Print the legal warning for continuous mode, the latest news bulletin, and warnings about the git branch and Python version.",
        lines=(7, 22),
    ),
    dict(
        id="stage:workspace",
        blurb="Workspace directory, log path, plugin scan.",
        title="Prepare workspace and plugins",
        label="Install plugin dependencies if asked, create the workspace directory, set the file-log path and scan for plugins.",
        lines=(23, 27),
    ),
    dict(
        id="stage:commands",
        blurb="Import command modules into the registry.",
        title="Register commands",
        label="Import every enabled command module and register its commands, so the agent knows what it can do.",
        lines=(28, 28),
    ),
    dict(
        id="stage:profile",
        blurb="Load or ask for the agent's name, role and goals.",
        title="Choose the AI profile",
        label="Load a saved AI profile or ask the user for the agent's name, role and goals, then attach the command registry to it.",
        lines=(29, 30),
    ),
    dict(
        id="stage:agent",
        blurb="Chat plugins, memory backend, then the Agent.",
        title="Assemble the agent",
        label="Collect chat plugins, open and clear the memory backend, and construct the Agent from memory, commands and profile.",
        lines=(31, 40),
    ),
    dict(
        id="stage:loop",
        blurb="Think, approve, execute. Repeat until exit.",
        title="Run the interaction loop",
        label="Think, show the plan, ask the user for approval, execute the command, repeat, until the user exits or the cycle budget runs out.",
        lines=(41, 41),
    ),
]

TYPE_MAP = {
    "StartNode": "start",
    "EndNode": "end",
    "ActionNode": "action",
    "DefineNode": "action",
    "CallNode": "call",
    "DecisionNode": "decision",
}

BAD_LABEL = re.compile(
    r"provided code snippet|lacks context|lacks actionable|\.\.__enter__|\.\.__exit__",
    re.I,
)


def parse_uuid(uuid: str):
    """'/mod/func:12:4:Assign:glue' -> (fn, line, col, ast_type, kind)."""
    fn, line, col, ast_type, kind = uuid.rsplit(":", 4)
    return fn, int(line), int(col), ast_type, kind


def short_fn(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def module_of(uri: str) -> str:
    return uri.strip("/").split("/")[0]


class FnSource:
    """Function source as stored in codeinfo.json (ast.unparse output, no docstring)."""

    def __init__(self, code: str):
        self.code = code
        self.lines = code.split("\n")
        self.index: dict[tuple[int, int, str], ast.AST] = {}
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if hasattr(node, "lineno"):
                self.index.setdefault(
                    (node.lineno, node.col_offset, type(node).__name__), node
                )

    def find(self, line: int, col: int, ast_type: str):
        return self.index.get((line, col, ast_type))

    def segment(self, node: ast.AST) -> str:
        return ast.get_source_segment(self.code, node) or ""

    def line_text(self, lo: int, hi: int) -> str:
        return textwrap.dedent("\n".join(self.lines[lo - 1 : hi]))


def header_of(node: ast.AST, src: FnSource) -> str:
    """First line of a compound statement, e.g. 'if not config.skip_news:'."""
    return src.lines[node.lineno - 1].strip()


def main() -> None:
    flat = json.loads(FLAT.read_text())["nodes"]
    elements = json.loads(ELEMENT.read_text())["flowchart"]
    codeinfo = json.loads(CODEINFO.read_text())["nodes"]

    parent_of = {
        e["data"]["id"]: e["data"]["parent"]
        for e in elements
        if e["group"] == "nodes"
    }

    sources: dict[str, FnSource] = {}

    def source(fn: str) -> FnSource | None:
        if fn not in sources:
            info = codeinfo.get(fn)
            sources[fn] = (
                FnSource(info["code"]) if info and info.get("code") else None
            )
        return sources[fn]

    # ---- 1. nodes -----------------------------------------------------------
    nodes: dict[str, dict] = {}
    for uuid, raw in flat.items():
        fn, line, col, ast_type, kind = parse_uuid(uuid)
        node = dict(
            id=uuid,
            type=TYPE_MAP[raw["type"]],
            kind=kind,
            label=raw["label"].strip(),
            parent=parent_of[uuid],
            children=[],
            fn=fn,
        )
        if raw.get("next"):
            node["next"] = raw["next"]
        if raw.get("true"):
            node["yes"] = raw["true"]
        if raw.get("false"):
            node["no"] = raw["false"]
        if raw.get("func_uri"):
            node["callee"] = raw["func_uri"]
        if raw.get("subchart"):
            node["_start"] = raw["subchart"]["start"]

        src = source(fn)
        found = src.find(line, col, ast_type) if src else None
        if found is not None:
            node["_ast"] = found
            node["lines"] = [found.lineno, found.end_lineno]
        elif src and 1 <= line <= len(src.lines):
            node["lines"] = [line, line]
        nodes[uuid] = node

    for uuid, node in nodes.items():
        if node["parent"] in nodes:
            nodes[node["parent"]]["children"].append(uuid)

    # A container's entry: the dump's subchart start when it is a direct child,
    # otherwise the child nothing else points at.
    for node in nodes.values():
        kids = node["children"]
        if not kids:
            continue
        start = node.pop("_start", None)
        if start in kids:
            node["entry"] = start
            continue
        targets = {nodes[k].get(key) for k in kids for key in ("next", "yes", "no")}
        heads = [k for k in kids if k not in targets]
        node["entry"] = heads[0] if heads else kids[0]
    for node in nodes.values():
        node.pop("_start", None)

    # ---- 2. code snippets and line ranges ----------------------------------
    def own_range(node_id: str):
        """Line range inside the node's own function, including same-function children."""
        node = nodes[node_id]
        lo, hi = node.get("lines", [None, None])
        for kid in node["children"]:
            if nodes[kid]["fn"] != node["fn"]:
                continue
            klo, khi = own_range(kid)
            if klo is None:
                continue
            lo = klo if lo is None else min(lo, klo)
            hi = khi if hi is None else max(hi, khi)
        return lo, hi

    for uuid, node in nodes.items():
        src = source(node["fn"])
        if not src:
            continue
        found = node.pop("_ast", None)
        kind = node["kind"]
        lo, hi = own_range(uuid)
        if lo is not None:
            node["lines"] = [lo, hi]
        if node["type"] in ("start", "end"):
            node.pop("lines", None)
            continue
        if kind in ("check_value",) and found is not None:
            node["code"] = f"if {src.segment(found)}:"
            node["lines"] = [found.lineno, found.end_lineno]
        elif kind in ("for_check", "for_fetch"):
            node["code"] = src.lines[node["lines"][0] - 1].strip()
            node["lines"] = [node["lines"][0], node["lines"][0]]
        elif kind == "except" and found is not None:
            node["code"] = header_of(found, src)
            node["lines"] = [found.lineno, found.lineno]
        elif kind in ("call", "enter_0", "exit_0") and found is not None:
            seg = src.segment(found)
            node["code"] = header_of(found, src) if kind != "call" else seg
            node["lines"] = [found.lineno, found.end_lineno]
        elif lo is not None:
            node["code"] = src.line_text(lo, hi)

    # ---- 3. label repairs and short titles ---------------------------------
    repaired = []
    for uuid, node in nodes.items():
        kind, code = node["kind"], node.get("code", "")
        label = node["label"]
        if kind == "for_check":
            m = re.match(r"for (.+?) in ", code)
            label = f"Is there another `{m.group(1)}` to process?" if m else label
        elif kind == "for_fetch":
            m = re.match(r"for (.+?) in ", code)
            label = f"Take the next `{m.group(1)}`." if m else label
        elif BAD_LABEL.search(label) or (
            kind == "glue" and label.startswith("Fetch ")
        ):
            if kind == "check_value":
                label = f"Check whether `{code[3:-1]}` is set."
            elif kind == "enter_0":
                label = "Start the spinner (enter the `with` block)."
            elif kind == "exit_0":
                label = "Stop the spinner (leave the `with` block)."
            elif kind == "glue":
                m = re.match(r"for (.+?) in (.+):$", code.split("\n")[0])
                label = (
                    f"Evaluate `{m.group(2)}` to get the items to loop over."
                    if m
                    else label
                )
        if label != node["label"]:
            repaired.append(uuid)
            node["label"] = label
            node["labelRepaired"] = True

    def title_of(node: dict) -> str:
        kind, code = node["kind"], node.get("code", "")
        first = code.split("\n")[0].strip() if code else ""
        if node["type"] == "call":
            return f"{short_fn(node['callee'])}()"
        if kind in (
            "if_wrapper",
            "for_wrapper",
            "while_wrapper",
            "with_wrapper",
            "try_wrapper",
        ):
            return first if len(first) <= 46 else first[:44] + "…"
        if kind in ("wrapper", "call_wrapper", "simple", "glue") and first:
            return first if len(first) <= 46 else first[:44] + "…"
        if kind == "nodes_wrapper":
            return f"{len(node['children'])} steps"
        return first or node["label"]

    for node in nodes.values():
        node["title"] = title_of(node)

    # ---- 4. Level 0: program root and hand-written stages ------------------
    body = next(
        n
        for n in nodes.values()
        if n["fn"] == ENTRY_FN
        and n["kind"] == "nodes_wrapper"
        and n["parent"] not in nodes
    )
    start_id = next(k for k, n in nodes.items() if n["type"] == "start")
    end_id = next(k for k, n in nodes.items() if n["type"] == "end")
    program_summary = body["label"]
    body_kids = body["children"]
    del nodes[body["id"]]

    stage_ids = [s["id"] for s in STAGES]
    for i, stage in enumerate(STAGES):
        lo, hi = stage["lines"]
        kids = [k for k in body_kids if lo <= nodes[k]["lines"][0] <= hi]
        assert kids, stage["id"]
        for k in kids:
            nodes[k]["parent"] = stage["id"]
            # links that leave the stage are carried by the stage itself
            for key in ("next", "yes", "no"):
                if nodes[k].get(key) and nodes[k][key] not in kids:
                    del nodes[k][key]
        nodes[stage["id"]] = dict(
            id=stage["id"],
            type="action",
            kind="stage",
            label=stage["label"],
            title=stage["title"],
            blurb=stage["blurb"],
            parent=ROOT_ID,
            children=kids,
            entry=kids[0],
            fn=ENTRY_FN,
            lines=[lo, hi],
            code=source(ENTRY_FN).line_text(lo, hi),
            authored=True,
            next=stage_ids[i + 1] if i + 1 < len(STAGES) else end_id,
        )
    assert sum(len(nodes[s]["children"]) for s in stage_ids) == len(body_kids)

    nodes[start_id].update(
        parent=ROOT_ID, next=stage_ids[0], title="Start", label="python -m autogpt"
    )
    nodes[end_id].update(parent=ROOT_ID, title="End", label="Process exits")
    nodes[ROOT_ID] = dict(
        id=ROOT_ID,
        type="action",
        kind="program",
        label="Auto-GPT starts up, builds an autonomous agent from configuration, commands, memory and an AI profile, then runs it in a think → approve → execute loop.",
        title="Program",
        parent=None,
        children=[start_id, *stage_ids, end_id],
        entry=start_id,
        fn=ENTRY_FN,
        authored=True,
        pipelineSummary=program_summary,
    )

    # ---- 5. functions ------------------------------------------------------
    wanted = {n["fn"] for n in nodes.values()} | {
        n["callee"] for n in nodes.values() if n.get("callee")
    }
    charted = defaultdict(list)  # callee uri -> call nodes that inline its flowchart
    for n in nodes.values():
        if n.get("callee") and n["children"]:
            charted[n["callee"]].append(n["id"])

    functions = {}
    for uri in sorted(wanted):
        info = codeinfo.get(uri)
        entry = dict(uri=uri, name=short_fn(uri), module=module_of(uri))
        if info:
            entry.update(
                code=info.get("code") or "",
                fileLine=info.get("lineno"),
                summary=(info.get("summary") or "").strip(),
                calls=sorted(info.get("calls") or []),
                calledBy=sorted(info.get("called_by") or []),
            )
        if uri in charted:
            entry["chart"] = charted[uri][0]
        functions[uri] = entry
    functions[ENTRY_FN]["chart"] = ROOT_ID

    def max_depth(node_id: str) -> int:
        kids = nodes[node_id]["children"]
        return 1 + max(map(max_depth, kids)) if kids else 0

    # size of the whole analysed repository, for the story section
    repo_counts = defaultdict(int)
    for info in codeinfo.values():
        repo_counts[info.get("type", "other")] += 1

    out = dict(
        meta=dict(
            repo="Auto-GPT",
            version="v0.4.7",
            entry="autogpt/app/cli.py → run_auto_gpt",
            root=ROOT_ID,
            entryFn=ENTRY_FN,
            nodeCount=len(nodes),
            functionCount=len(functions),
            chartedFunctions=len({n["fn"] for n in nodes.values()}),
            depth=max_depth(ROOT_ID),
            repoCounts=repo_counts,
        ),
        nodes=nodes,
        functions=functions,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")

    with_code = sum(1 for n in nodes.values() if n.get("code"))
    print(f"wrote {OUT.relative_to(REPO)}  ({OUT.stat().st_size / 1024:.0f} KB)")
    print(
        f"  nodes: {len(nodes)}  with code: {with_code}  labels repaired: {len(repaired)}"
    )
    print(f"  functions: {len(functions)}  with flowchart: {len(charted) + 1}")


if __name__ == "__main__":
    main()
