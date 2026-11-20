"""Rewrite the statement labels with the whole function in view.

The 2023 labels were written one statement at a time, so many restate the syntax
("Verify that `x` is set to True") and some misread it, because the model never saw
what came before or after. This pass asks once per function: here is its source, here
are its flowchart steps, say what each step does in the program's terms. Blocks whose
box title is just the first line of their code (an `if`, a run of "3 steps") also get a
real title.

Answers live in codezoom/cache/labels.json, keyed by function and source, so a build is
deterministic and needs no key. Functions with no cached answer keep their 2023 labels
and are written to codezoom/cache/pending_labels.json.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from .graph import ROOT, Tree, short_fn

CACHE = Path(__file__).parent / "cache" / "labels.json"
PENDING = Path(__file__).parent / "cache" / "pending_labels.json"

INSTRUCTIONS = """Each request below is one Python function from Auto-GPT v0.4.7 (an autonomous \
agent: the user gives it a name, a role and goals; each cycle it asks an OpenAI model what to do, \
shows the plan, and runs the chosen command once the user approves). The function's source has \
numbered lines. After it come the steps of the function's flowchart: a key, the step's kind, \
its code, and an old label to replace.

For every step write a "label": one plain sentence under 20 words saying what the step does \
and what it is for, in the program's terms (the agent, the user, the settings, the commands), \
not a restatement of the syntax. Read the surrounding code so you describe conditions and \
their effects correctly. A decision (kind check_value, for_check or except) is a yes/no \
question, e.g. "Did the user type exit?". A block (it has steps inside) summarises what the \
whole block does. Steps marked TITLE also need a "title": 2 to 5 words, sentence case, no \
trailing period, naming the block's job; it replaces the code shown as the box title.

Answer with one JSON object. Keys are the request keys; each value maps step keys to \
{"label": "..."} or {"label": "...", "title": "..."}."""

# blocks whose box title would otherwise be code or "N steps"
NEEDS_TITLE = {
    "if_wrapper",
    "nodes_wrapper",
    "for_wrapper",
    "while_wrapper",
    "try_wrapper",
    "with_wrapper",
}


def local(node_id: str) -> str:
    return node_id.rsplit("/", 1)[-1].split(":", 1)[1]


def key_of(fn: str, source: str) -> str:
    return "L" + hashlib.sha1((fn + "\n" + source).encode()).hexdigest()[:14]


def needs_title(tree: Tree, node_id: str) -> bool:
    n = tree[node_id]
    return bool(n.children) and n.kind in NEEDS_TITLE


def render(tree: Tree, fn: str, steps: list[str]) -> str:
    info = tree.codeinfo.get(fn) or {}
    src = info.get("code") or ""
    numbered = "\n".join(
        f"{i:3d}  {line}" for i, line in enumerate(src.split("\n"), 1)
    )
    out = [
        f"### request {key_of(fn, src)}",
        f"Function: {short_fn(fn)}",
        numbered,
        "Steps:",
    ]
    for s in steps:
        n = tree[s]
        code = (n.code or "").split("\n")
        head = " / ".join(c.strip() for c in code[:3]) + (
            " …" if len(code) > 3 else ""
        )
        mark = " TITLE" if needs_title(tree, s) else ""
        line = f"- {local(s)} [{n.kind}{mark}] code: {head} | old label: {n.label}"
        if n.callee:
            summary = (tree.codeinfo.get(n.callee) or {}).get("summary") or ""
            line += f" | calls {short_fn(n.callee)}: {summary.strip()[:200]}"
        out.append(line)
    return "\n".join(out)


def relabel(tree: Tree, use_cache: bool = True) -> tuple[int, int]:
    """Apply cached labels; write requests for functions without one. Returns (applied, pending)."""
    cache = json.loads(CACHE.read_text()) if use_cache and CACHE.exists() else {}
    by_fn: dict[str, list[str]] = defaultdict(list)
    for node in tree.nodes.values():
        if node.id != ROOT:
            by_fn[node.fn].append(node.id)
    pending: dict[str, str] = {}
    applied = 0
    for fn, steps in sorted(by_fn.items()):
        src = (tree.codeinfo.get(fn) or {}).get("code") or ""
        key = key_of(fn, src)
        answer = cache.get(key)
        if not isinstance(answer, dict):
            pending[key] = render(tree, fn, steps)
            continue
        for s in steps:
            got = answer.get(local(s))
            if not isinstance(got, dict) or not got.get("label"):
                continue
            n = tree[s]
            n.old_label, n.label, n.relabeled = n.label, got["label"].strip(), True
            if got.get("title") and needs_title(tree, s):
                n.title = got["title"].strip().rstrip(".")
            applied += 1
    if pending:
        PENDING.write_text(
            json.dumps({"instructions": INSTRUCTIONS, "requests": pending}, indent=1)
            + "\n"
        )
    elif PENDING.exists():
        PENDING.unlink()
    return applied, len(pending)


TITLES = """Each entry below is a block in a flowchart of Auto-GPT v0.4.7 whose box is titled with \
code. Give it a title: 2 to 5 words, sentence case, no trailing period, naming what the block does in \
the program's terms (use its label). Answer with one JSON object mapping each entry key to its title."""


def code_titled(tree: Tree, node_id: str) -> bool:
    """A block (it opens) whose box title is still a line of code or a function name."""
    n = tree[node_id]
    if not n.children or n.kind in ("group", "program"):
        return False
    first = (n.code or "").split("\n")[0].strip()
    return n.title.endswith("()") or (bool(first) and n.title.startswith(first[:20]))


def titles(tree: Tree, use_cache: bool = True) -> tuple[int, int]:
    """After rebalancing: real titles for blocks still titled with code. Returns (applied, pending)."""
    cache = json.loads(CACHE.read_text()) if use_cache and CACHE.exists() else {}
    pending: dict[str, str] = {}
    applied = 0
    for node in tree.nodes.values():
        if not code_titled(tree, node.id):
            continue
        key = "T:" + node.id
        if isinstance(cache.get(key), str) and cache[key].strip():
            node.title = cache[key].strip().rstrip(".")
            applied += 1
        else:
            code = " / ".join((node.code or "").split("\n")[:2])
            pending[key] = f"- {key} | code: {code} | label: {node.label}"
    if pending:
        body = json.loads(PENDING.read_text()) if PENDING.exists() else {}
        body.update(titles_instructions=TITLES, titles=pending)
        PENDING.write_text(json.dumps(body, indent=1) + "\n")
    return applied, len(pending)


def merge(answers: dict) -> int:
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    cache.update(answers)
    CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True) + "\n")
    return len(answers)
