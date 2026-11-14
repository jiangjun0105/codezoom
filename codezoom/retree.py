"""Rebuild the syntactic tree into a balanced one for zooming.

The tree that comes out of the 2023 pipeline mirrors the syntax: 276 blocks, 160 of
them with just two children, statements up to 21 levels down. Zooming through it is a
long walk through `x = f()` wrappers and one-armed ifs, while a few functions show 13
or 21 steps at once.

This pass keeps every statement and every control-flow edge, and changes only how
they are bundled, with two operations:

    expand(c)   replace a step by the chart inside it (the chart gets finer)
    group(run)  bundle a run of steps into one new step (the chart gets coarser)

A chart is expanded while it is too small or one step holds most of its statements,
and grouped when it has more steps than fit on a screen. Small charts are expanded
all the way, so the last level is a real statement-level flowchart with its branches.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from . import segment
from .features import Features
from .graph import ROOT, Node, Tree, short_fn
from .oracle import Oracle


@dataclass
class Config:
    min_fan: int = 3  # expand while a chart has fewer steps than this
    max_fan: int = 7  # group when a chart has more steps than this
    root_fan: int = 8  # the top level may show one more
    dominant: float = (
        0.6  # expand a step that holds more than this share of the statements
    )
    leaf_budget: int = (
        10  # a chart with at most this many statements is shown in full
    )
    balance: float = 0.5
    signals: tuple[float, float, float] = (1.0, 1.0, 1.0)  # flow, data, lexical


def simplify(tree: Tree) -> int:
    """`x = f()` is stored as a wrapper holding the call and a "store the result" step.

    Fold the pair into the wrapper: it becomes the call, with the callee's chart (if
    any) directly inside. Returns how many wrappers were folded.
    """
    folded = 0
    for node in list(tree.nodes.values()):
        if node.kind not in ("wrapper", "call_wrapper") or len(node.children) != 2:
            continue
        kids = [tree[k] for k in node.children]
        call = next((k for k in kids if k.type == "call"), None)
        glue = next((k for k in kids if k.kind == "glue"), None)
        if not call or not glue:
            continue
        node.type, node.callee = "call", call.callee
        node.children, node.entry = call.children, call.entry
        for k in node.children:
            tree[k].parent = node.id
        tree.aliases[call.id] = tree.aliases[glue.id] = node.id
        del tree.nodes[call.id], tree.nodes[glue.id]
        folded += 1
    tree._leaves.clear()
    return folded


def expand(tree: Tree, scope: str, c: str) -> None:
    """Replace step `c` of `scope` by its own steps, rewiring the edges around it."""
    s, node = tree[scope], tree[c]
    after = node.next
    # anything that led to the step now leads to its first inner step (also from inside finished groups)
    for other in tree.nodes.values():
        for key in ("next", "yes", "no"):
            if getattr(other, key) == c:
                setattr(other, key, node.entry)
    inner = set(node.children)
    for k in node.children:
        kid = tree[k]
        kid.parent = scope
        if kid.type == "decision":
            # a branch with no target falls through to whatever follows the block
            kid.yes = kid.yes or after
            kid.no = kid.no or after
        elif not kid.next or kid.next not in inner:
            kid.next = after
    at = s.children.index(c)
    s.children[at : at + 1] = node.children
    if s.entry == c:
        s.entry = node.entry
    if node.callee and node.type == "call":
        s.via.append(short_fn(node.callee))
    s.via.extend(node.via)
    tree.aliases[c] = node.entry
    if node.callee:
        tree.fn_charts.setdefault(node.callee, node.entry)
    del tree.nodes[c]


def sese(tree: Tree, steps: list[str]) -> list[list[bool]]:
    """valid[i][j]: steps i..j-1 have a single way in (their first step) and a single way out."""
    n = len(steps)
    index = {s: i for i, s in enumerate(steps)}
    # where each step can go next; n stands for "leaves this chart", including a branch with no target
    out = []
    for s in steps:
        node = tree[s]
        targets = [node.yes, node.no] if node.type == "decision" else [node.next]
        out.append([index.get(t, n) if t else n for t in targets])
    preds: list[list[int]] = [[] for _ in range(n)]
    for i, targets in enumerate(out):
        for t in targets:
            if t < n:
                preds[t].append(i)
    valid = [[False] * (n + 1) for _ in range(n + 1)]
    for i in range(n):
        for j in range(i + 2, n + 1):
            enters_ok = all(i <= p < j for m in range(i + 1, j) for p in preds[m])
            exits = {t for m in range(i, j) for t in out[m] if not i <= t < j}
            valid[i][j] = enters_ok and len(exits) <= 1
    return valid


def group_id(members: list[str]) -> str:
    return "group:" + hashlib.sha1("|".join(members).encode()).hexdigest()[:10]


def fallback_text(tree: Tree, members: list[str]) -> tuple[str, str]:
    """Title and summary for a group when no model answer is cached: lean on the heaviest member."""
    lead = tree[max(members, key=tree.weight)]
    rest = len(members) - 1
    label = lead.label.rstrip(".") + (
        f", and {rest} more step{'s' if rest > 1 else ''}." if rest else "."
    )
    return lead.title, label


def group(
    tree: Tree, scope: str, cfg: Config, oracle: Oracle | None = None
) -> list[str]:
    """Bundle the steps of an over-full chart into consecutive single-entry, single-exit groups."""
    s = tree[scope]
    steps = tree.flow_order(scope)
    limit = cfg.root_fan if scope == ROOT else cfg.max_fan
    valid = sese(tree, steps)
    text: dict[int, tuple[str, str]] = {}
    answer = oracle.grouping(tree, scope, steps, limit) if oracle else None
    if answer:
        starts = [g["start"] for g in answer]
        ends = starts[1:] + [len(steps)]
        if all(b - a == 1 or valid[a][b] for a, b in zip(starts, ends)):
            text = {g["start"]: (g["title"], g["summary"]) for g in answer}
        else:
            answer = (
                None  # a proposed group has two ways in or out; use the segmenter
            )
    if not answer:
        feats = Features(tree, steps)
        k = segment.group_count(len(steps), cfg.min_fan, limit)
        starts = segment.min_cut_dp(
            feats.affinity(*cfg.signals), k, feats.weights, cfg.balance, valid
        )
    tree.grouped_by[scope] = "model" if answer else "segmenter"
    bounds = starts + [len(steps)]
    owner: dict[str, str] = {}
    made: list[str] = []
    chart: list[str] = []
    for a, b in zip(bounds, bounds[1:]):
        members = steps[a:b]
        if len(members) == 1:
            chart.append(members[0])
            continue
        gid = group_id(members)
        g = Node(
            id=gid,
            type="action",
            kind="group",
            label="",
            fn=tree[members[0]].fn,
            parent=scope,
            generated=True,
        )
        g.children, g.entry = members, members[0]
        named = text.get(a) or (
            oracle.name(tree, scope, members) if oracle else None
        )
        g.title, g.label = named or fallback_text(tree, members)
        g.named_by = "model" if named else "fallback"
        tree.nodes[gid] = g
        for m in members:
            owner[m] = gid
            tree[m].parent = gid
        made.append(gid)
        chart.append(gid)
    # edges between chart steps: a link into a group lands on the group
    for gid in made:
        g = tree[gid]
        outside = {
            t for m in g.children for _, t in tree[m].links() if owner.get(t) != gid
        }
        g.next = (
            owner.get(next(iter(outside)), next(iter(outside))) if outside else None
        )
    for cid in chart:
        node = tree[cid]
        if node.kind == "group" and node.generated and cid in made:
            continue
        for key in ("next", "yes", "no"):
            target = getattr(node, key)
            if target in owner:
                setattr(node, key, owner[target])
    s.children = chart
    s.entry = owner.get(s.entry, s.entry)
    tree._leaves.clear()
    return made


def normalize(
    tree: Tree, scope: str, cfg: Config, oracle: Oracle | None = None
) -> None:
    s = tree[scope]
    if not s.children:
        return
    if tree.weight(scope) <= cfg.leaf_budget:
        # small enough to show as one statement-level flowchart
        while True:
            c = next((k for k in s.children if tree[k].children), None)
            if c is None:
                return
            expand(tree, scope, c)
    while True:
        total = tree.weight(scope)
        open_steps = [
            k for k in s.children if tree[k].children and tree[k].kind != "group"
        ]
        if not open_steps:
            break
        heaviest = max(open_steps, key=tree.weight)
        if (
            len(s.children) < cfg.min_fan
            or tree.weight(heaviest) / total > cfg.dominant
        ):
            expand(tree, scope, heaviest)
        else:
            break
    limit = cfg.root_fan if scope == ROOT else cfg.max_fan
    if len(s.children) > limit:
        group(tree, scope, cfg, oracle)
    for k in list(s.children):
        normalize(tree, k, cfg, oracle)


def retree(
    tree: Tree, cfg: Config | None = None, oracle: Oracle | None = None
) -> Tree:
    """Rebalance the tree in place and return it."""
    cfg = cfg or Config()
    simplify(tree)
    normalize(tree, ROOT, cfg, oracle)
    tree._leaves.clear()
    return tree


def shape(tree: Tree) -> dict[str, float]:
    """Numbers that describe how the tree feels to zoom through."""
    charts = [n for n in tree.nodes.values() if n.children]
    fans = [len(n.children) for n in charts]
    leaves = [n.id for n in tree.nodes.values() if not n.children]
    depths = [tree.depth(leaf) for leaf in leaves]
    comfy = sum(3 <= f <= 8 for f in fans)
    return {
        "charts": len(charts),
        "statements": len(leaves),
        "max_depth": max(depths),
        "mean_depth": sum(depths) / len(depths),
        "charts_with_2_or_fewer": sum(f <= 2 for f in fans),
        "charts_with_over_8": sum(f > 8 for f in fans),
        "share_3_to_8": comfy / len(fans),
        "widest": max(fans),
    }
