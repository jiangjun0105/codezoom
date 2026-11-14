"""Signals for deciding which neighbouring steps belong together.

Three kinds of evidence, each a symmetric matrix over the steps of one chart:
    flow     the steps are linked by a control-flow edge
    data     one step writes a name the other reads (rare names count more)
    lexical  their labels and identifiers use the same words (TF-IDF cosine)
"""
from __future__ import annotations

import ast
import math
import re
from collections import Counter

from .graph import Tree

STOP = set(
    "a an the and or of to in on for with by from into as is are be if it its this that then than not no "
    "set sets store stores stored get gets using use used based given provided specified value values "
    "variable variables check checks whether display displays log logs message".split()
)
WORD = re.compile(r"[A-Za-z][a-z]+|[A-Z]+(?![a-z])")


def words(text: str) -> list[str]:
    out = []
    for w in WORD.findall(text):
        w = w.lower()
        if len(w) < 3 or w in STOP:
            continue
        for suffix in ("ing", "es", "ed", "s"):
            if w.endswith(suffix) and len(w) - len(suffix) >= 3:
                w = w[: -len(suffix)]
                break
        out.append(w)
    return out


def names(code: str) -> tuple[set[str], set[str]]:
    """(written, read) names of a snippet. Attribute chains count as `a.b`; a write to `a.b` also touches `a`."""
    written: set[str] = set()
    read: set[str] = set()
    tree = None
    for candidate in (code, code + "\n    pass", "(" + code + ")"):
        try:
            tree = ast.parse(candidate)
            break
        except SyntaxError:
            continue
    if tree is None:
        return written, set(re.findall(r"[A-Za-z_]\w*", code))

    def dotted(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = dotted(node.value)
            return f"{base}.{node.attr}" if base else None
        if isinstance(node, ast.Subscript):
            base = dotted(node.value)
            key = node.slice.value if isinstance(node.slice, ast.Constant) else None
            return f"{base}[{key}]" if base and isinstance(key, str) else base
        return None

    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)):
            name = dotted(node)
            if not name:
                continue
            store = isinstance(getattr(node, "ctx", None), ast.Store)
            (written if store else read).add(name)
            if store and "." in name or "[" in name:
                read.add(re.split(r"[.\[]", name)[0])
    return written, read


class Features:
    """Per-step evidence for the steps of one chart, in execution order."""

    def __init__(self, tree: Tree, steps: list[str]):
        self.tree = tree
        self.steps = steps
        n = len(steps)
        nodes = [tree[s] for s in steps]
        self.weights = [tree.weight(s) for s in steps]

        index = {s: i for i, s in enumerate(steps)}
        self.flow = [[0.0] * n for _ in range(n)]
        for i, node in enumerate(nodes):
            for _, target in node.links():
                if target in index and index[target] != i:
                    j = index[target]
                    self.flow[i][j] = self.flow[j][i] = 1.0

        io = [names(node.code or "") for node in nodes]
        mention = Counter(name for w, r in io for name in w | r)
        idf = {name: math.log((n + 1) / (c + 0.5)) for name, c in mention.items()}
        self.data = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                shared = (
                    (io[i][0] & io[j][1])
                    | (io[j][0] & io[i][1])
                    | (io[i][0] & io[j][0])
                )
                self.data[i][j] = self.data[j][i] = sum(
                    max(idf[v], 0.0) for v in shared
                )
        peak = max((v for row in self.data for v in row), default=0.0)
        if peak > 0:
            self.data = [[v / peak for v in row] for row in self.data]

        bags = [
            Counter(words(node.label) + words(node.code or "")[:60])
            for node in nodes
        ]
        df = Counter(w for bag in bags for w in bag)
        vecs = [
            {
                w: (1 + math.log(c)) * math.log((n + 1) / (df[w] + 0.5))
                for w, c in bag.items()
            }
            for bag in bags
        ]
        norms = [math.sqrt(sum(v * v for v in vec.values())) or 1.0 for vec in vecs]
        self.lexical = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                dot = sum(v * vecs[j].get(w, 0.0) for w, v in vecs[i].items())
                self.lexical[i][j] = self.lexical[j][i] = max(dot, 0.0) / (
                    norms[i] * norms[j]
                )

    def affinity(
        self,
        flow: float = 1.0,
        data: float = 1.0,
        lexical: float = 1.0,
        reach: int = 3,
    ) -> list[list[float]]:
        """Weighted sum of the three signals. Data and lexical ties fade with distance in the order."""
        n = len(self.steps)
        out = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                fade = 1.0 if j - i <= 1 else max(0.0, 1 - (j - i - 1) / reach)
                v = flow * self.flow[i][j] + fade * (
                    data * self.data[i][j] + lexical * self.lexical[i][j]
                )
                out[i][j] = out[j][i] = v
        return out
