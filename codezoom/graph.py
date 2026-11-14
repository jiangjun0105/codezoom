"""Load the 2023 pipeline's dumps into one syntactic tree.

Inputs (Auto-GPT v0.4.7, entry point run_auto_gpt):
    convert_dump/linked_flat.json        nodes, labels, next / true / false links
    convert_dump/linked_element.json     the compound-node parent of every node
    shared_cache/Auto-GPT/codeinfo.json  function source, summaries, call graph

The dumps carry `code: null`, so the snippet and line range of each node are recovered
here by re-parsing the cached function source and matching `line:col:AstType` from the
node id.
"""
from __future__ import annotations

import ast
import json
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FLAT = REPO / "convert_dump" / "linked_flat.json"
ELEMENT = REPO / "convert_dump" / "linked_element.json"
CODEINFO = REPO / "shared_cache" / "Auto-GPT" / "codeinfo.json"

ROOT = "program"

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


@dataclass
class Node:
    id: str
    type: str  # action | call | decision
    kind: str  # last part of the pipeline id (wrapper, if_wrapper, simple, ...) or program / group
    label: str
    fn: str  # uri of the function whose source this node comes from
    parent: str | None = None
    children: list[str] = field(default_factory=list)
    entry: str | None = None
    next: str | None = None
    yes: str | None = None
    no: str | None = None
    callee: str | None = None
    lines: tuple[int, int] | None = None
    code: str | None = None
    title: str = ""
    label_repaired: bool = False
    # filled by the abstraction step
    blurb: str | None = None
    via: list[str] = field(default_factory=list)
    generated: bool = False
    named_by: str | None = None
    # a one-armed `if`: the test under which this step runs at all (otherwise it is skipped)
    guard: str | None = None
    # a `for` or `while` block
    loop: bool = False

    def links(self) -> list[tuple[str, str]]:
        return [(k, v) for k in ("next", "yes", "no") if (v := getattr(self, k))]


class FnSource:
    """Function source as cached by the pipeline (ast.unparse output)."""

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


def short_fn(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def module_of(uri: str) -> str:
    return uri.strip("/").split("/")[0]


class Tree:
    """The syntactic tree: every block and every inlined callee is a node with children."""

    def __init__(
        self,
        nodes: dict[str, Node],
        codeinfo: dict,
        entry_fn: str,
        pipeline_summary: str = "",
    ):
        self.nodes = nodes
        self.codeinfo = codeinfo
        self.entry_fn = entry_fn
        self.pipeline_summary = pipeline_summary
        self._leaves: dict[str, int] = {}
        # id of a step that was folded or expanded away -> the step or chart that absorbed it
        self.aliases: dict[str, str] = {}
        self.grouped_by: dict[str, str] = {}
        # id of an expanded step -> the steps that were inside it
        self.expanded: dict[str, list[str]] = {}
        # callee uri -> first step of its chart, for callees whose call step was expanded away
        self.fn_charts: dict[str, str] = {}

    def __getitem__(self, node_id: str) -> Node:
        return self.nodes[node_id]

    def weight(self, node_id: str) -> int:
        """Number of leaf statements under a node."""
        if node_id not in self._leaves:
            kids = self.nodes[node_id].children
            self._leaves[node_id] = sum(self.weight(k) for k in kids) if kids else 1
        return self._leaves[node_id]

    def flow_order(self, node_id: str) -> list[str]:
        """Children in execution order: depth-first from the entry, `next` / `yes` before `no`."""
        node = self.nodes[node_id]
        kids = set(node.children)
        seen: list[str] = []
        stack = [node.entry or (node.children[0] if node.children else None)]
        while stack:
            cur = stack.pop()
            if cur is None or cur in seen or cur not in kids:
                continue
            seen.append(cur)
            n = self.nodes[cur]
            for target in (n.no, n.yes, n.next):
                if target:
                    stack.append(target)
        return seen + [k for k in node.children if k not in seen]

    def depth(self, node_id: str) -> int:
        d = 0
        while (p := self.nodes[node_id].parent) is not None:
            node_id, d = p, d + 1
        return d

    def lineage(self, node_id: str) -> list[str]:
        out = []
        cur: str | None = node_id
        while cur is not None:
            out.append(cur)
            cur = self.nodes[cur].parent
        return out[::-1]


def _parse_uuid(uuid: str):
    fn, line, col, ast_type, kind = uuid.rsplit(":", 4)
    return fn, int(line), int(col), ast_type, kind


def make_title(node: Node) -> str:
    first = node.code.split("\n")[0].strip() if node.code else ""
    if node.type == "call" and node.callee:
        return f"{short_fn(node.callee)}()"
    if node.kind == "nodes_wrapper":
        return f"{len(node.children)} steps"
    if first:
        return first if len(first) <= 46 else first[:44] + "…"
    return node.label


def load(entry_fn: str = "/autogpt.app.main/run_auto_gpt") -> Tree:
    flat = json.loads(FLAT.read_text())["nodes"]
    elements = json.loads(ELEMENT.read_text())["flowchart"]
    codeinfo = json.loads(CODEINFO.read_text())["nodes"]
    parent_of = {
        e["data"]["id"]: e["data"]["parent"]
        for e in elements
        if e["group"] == "nodes"
    }

    sources: dict[str, FnSource | None] = {}

    def source(fn: str) -> FnSource | None:
        if fn not in sources:
            info = codeinfo.get(fn)
            sources[fn] = (
                FnSource(info["code"]) if info and info.get("code") else None
            )
        return sources[fn]

    nodes: dict[str, Node] = {}
    found_ast: dict[str, ast.AST] = {}
    starts: dict[str, str] = {}
    for uuid, raw in flat.items():
        fn, line, col, ast_type, kind = _parse_uuid(uuid)
        node = Node(
            id=uuid,
            type=TYPE_MAP[raw["type"]],
            kind=kind,
            label=raw["label"].strip(),
            fn=fn,
            parent=parent_of[uuid],
            next=raw.get("next"),
            yes=raw.get("true"),
            no=raw.get("false"),
            callee=raw.get("func_uri"),
        )
        if raw.get("subchart"):
            starts[uuid] = raw["subchart"]["start"]
        src = source(fn)
        found = src.find(line, col, ast_type) if src else None
        if found is not None:
            found_ast[uuid] = found
            node.lines = (found.lineno, found.end_lineno)
        elif src and 1 <= line <= len(src.lines):
            node.lines = (line, line)
        nodes[uuid] = node

    for uuid, node in nodes.items():
        if node.parent in nodes:
            nodes[node.parent].children.append(uuid)

    for uuid, node in nodes.items():
        kids = node.children
        if not kids:
            continue
        if starts.get(uuid) in kids:
            node.entry = starts[uuid]
            continue
        targets = {t for k in kids for _, t in nodes[k].links()}
        heads = [k for k in kids if k not in targets]
        node.entry = heads[0] if heads else kids[0]

    # code snippets and line ranges
    def own_range(node_id: str):
        node = nodes[node_id]
        lo, hi = node.lines or (None, None)
        for kid in node.children:
            if nodes[kid].fn != node.fn:
                continue
            klo, khi = own_range(kid)
            if klo is None:
                continue
            lo = klo if lo is None else min(lo, klo)
            hi = khi if hi is None else max(hi, khi)
        return lo, hi

    for uuid, node in nodes.items():
        src = source(node.fn)
        if not src or node.type in ("start", "end"):
            node.lines = None
            continue
        found = found_ast.get(uuid)
        lo, hi = own_range(uuid)
        if lo is not None:
            node.lines = (lo, hi)
        kind = node.kind
        if kind == "check_value" and found is not None:
            node.code = f"if {src.segment(found)}:"
            node.lines = (found.lineno, found.end_lineno)
        elif kind in ("for_check", "for_fetch") and node.lines:
            node.code = src.lines[node.lines[0] - 1].strip()
            node.lines = (node.lines[0], node.lines[0])
        elif kind == "except" and found is not None:
            node.code = src.lines[found.lineno - 1].strip()
            node.lines = (found.lineno, found.lineno)
        elif kind == "call" and found is not None:
            node.code = src.segment(found)
            node.lines = (found.lineno, found.end_lineno)
        elif kind in ("enter_0", "exit_0") and found is not None:
            node.code = src.lines[found.lineno - 1].strip()
            node.lines = (found.lineno, found.lineno)
        elif lo is not None:
            node.code = src.line_text(lo, hi)

    # repairs for labels where the 2023 LLM call failed or a string template leaked
    for node in nodes.values():
        code, label = node.code or "", node.label
        loop = re.match(r"for (.+?) in (.+):$", code.split("\n")[0])
        if node.kind == "for_check" and loop:
            label = f"Is there another `{loop.group(1)}` to process?"
        elif node.kind == "for_fetch" and loop:
            label = f"Take the next `{loop.group(1)}`."
        elif BAD_LABEL.search(label) or (
            node.kind == "glue" and label.startswith("Fetch ")
        ):
            if node.kind == "check_value":
                label = f"Check whether `{code[3:-1]}` is set."
            elif node.kind == "enter_0":
                label = "Start the spinner (enter the `with` block)."
            elif node.kind == "exit_0":
                label = "Stop the spinner (leave the `with` block)."
            elif node.kind == "glue" and loop:
                label = f"Evaluate `{loop.group(2)}` to get the items to loop over."
        if label != node.label:
            node.label, node.label_repaired = label, True

    # steps that may be skipped or repeated, so charts above statement level can still show branching
    for node in nodes.values():
        if node.kind in ("for_wrapper", "while_wrapper"):
            node.loop = True
        if node.kind == "if_wrapper" and node.entry:
            test = nodes[node.entry]
            if test.type == "decision" and test.yes and not test.no and test.code:
                node.guard = test.code[3:].rstrip(":")

    # The dump's root is Start -> one "process of N nodes" block -> End. Make that block the root.
    body = next(
        n
        for n in nodes.values()
        if n.fn == entry_fn and n.kind == "nodes_wrapper" and n.parent not in nodes
    )
    for n in [n for n in nodes.values() if n.type in ("start", "end")]:
        del nodes[n.id]
    del nodes[body.id]
    root = Node(
        id=ROOT,
        type="action",
        kind="program",
        label="",
        fn=entry_fn,
        children=body.children,
        entry=body.entry,
    )
    nodes[ROOT] = root
    for kid in root.children:
        nodes[kid].parent = ROOT
    for n in nodes.values():
        for key in ("next", "yes", "no"):
            if getattr(n, key) and getattr(n, key) not in nodes:
                setattr(n, key, None)
    for n in nodes.values():
        n.title = make_title(n)
    root.title = "Program"
    return Tree(nodes, codeinfo, entry_fn, pipeline_summary=body.label)
