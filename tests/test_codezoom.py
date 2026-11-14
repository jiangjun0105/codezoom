"""Tests for the abstraction pass. Run with: python3 -m pytest tests"""
import copy

import pytest

from codezoom import segment
from codezoom.features import Features, names, words
from codezoom.graph import ROOT, load
from codezoom.retree import Config, expand, retree, sese, shape, simplify


@pytest.fixture(scope="module")
def raw():
    return load()


@pytest.fixture()
def tree(raw):
    return copy.deepcopy(raw)


def statements(tree):
    """Leaf statements with code, as (function, first line) pairs."""
    return sorted(
        (n.fn, n.lines) for n in tree.nodes.values() if not n.children and n.lines
    )


def check_integrity(tree):
    ids = set(tree.nodes)
    for n in tree.nodes.values():
        for _, target in n.links():
            assert target in ids, f"{n.id} links to a missing step"
        for c in n.children:
            assert tree[c].parent == n.id
        if n.children:
            assert n.entry in n.children
            assert sorted(tree.flow_order(n.id)) == sorted(n.children)
    assert tree[ROOT].parent is None


def test_load(raw):
    assert len(raw[ROOT].children) == 21
    assert raw.weight(ROOT) == 504
    check_integrity(raw)


def test_names_reads_and_writes():
    written, read = names("config.workspace_path = Workspace.init(config)")
    assert "config.workspace_path" in written
    assert {"config", "Workspace.init"} <= read
    assert names("if not config.skip_news:")[1] >= {"config.skip_news"}


def test_words_drops_filler():
    assert "configuration" in words("Set the configuration to the value")
    assert "the" not in words("Set the configuration to the value")


def test_segmenters_return_valid_partitions(raw):
    f = Features(raw, raw.flow_order(ROOT))
    a = f.affinity()
    for starts in (
        segment.uniform(21, 6),
        segment.weight_balanced(f.weights, 6),
        segment.modularity_dp(a, kmin=3, kmax=8),
        segment.min_cut_dp(a, 6, f.weights),
        segment.louvain(a)[0],
    ):
        assert starts[0] == 0 and starts == sorted(set(starts)) and starts[-1] < 21


def test_min_cut_respects_validity(raw):
    f = Features(raw, raw.flow_order(ROOT))
    valid = [[False] * 22 for _ in range(22)]
    for i in range(0, 21, 3):
        valid[i][min(i + 3, 21)] = True
    starts = segment.min_cut_dp(f.affinity(), 4, f.weights, valid=valid)
    bounds = starts + [21]
    assert all(b - a == 1 or valid[a][b] for a, b in zip(bounds, bounds[1:]))


def test_sese_rejects_half_a_branch(tree):
    simplify(tree)
    loop = next(
        n
        for n in tree.nodes.values()
        if n.kind == "while_wrapper" and n.fn.endswith("run_interaction_loop")
    )
    parent = loop.parent
    expand(tree, parent, loop.id)
    steps = tree.flow_order(parent)
    valid = sese(tree, steps)
    test = next(i for i, s in enumerate(steps) if tree[s].type == "decision")
    # the loop test has two ways out, so it cannot be bundled with the setup steps before it
    assert not valid[test - 1][test + 1]
    # the test plus the whole loop body leaves only one way out
    assert valid[test][len(steps)]


def test_expand_keeps_every_statement_reachable(tree):
    before = statements(tree)
    simplify(tree)
    folded = statements(tree)
    big = max((k for k in tree[ROOT].children if tree[k].children), key=tree.weight)
    expand(tree, ROOT, big)
    check_integrity(tree)
    assert statements(tree) == folded
    assert len(folded) <= len(before)


@pytest.mark.parametrize(
    "cfg",
    [Config(), Config(max_fan=5, leaf_budget=6), Config(dominant=0.9, min_fan=2)],
)
def test_retree_is_lossless_and_bounded(tree, cfg):
    simplify(tree)
    kept = statements(tree)
    retree(tree, cfg)
    check_integrity(tree)
    assert statements(tree) == kept, "rebalancing must not add or drop statements"
    for n in tree.nodes.values():
        if n.kind == "group":
            assert len(n.children) >= 2 and n.title and n.label
    s = shape(tree)
    assert s["max_depth"] < 12
    assert s["widest"] <= max(cfg.leaf_budget, cfg.root_fan, cfg.max_fan) + 3


def test_retree_is_deterministic(raw):
    a, b = copy.deepcopy(raw), copy.deepcopy(raw)
    retree(a), retree(b)
    assert {k: v.children for k, v in a.nodes.items()} == {
        k: v.children for k, v in b.nodes.items()
    }


def test_aliases_resolve_to_surviving_steps(tree):
    retree(tree)
    for old, new in tree.aliases.items():
        seen = set()
        while new in tree.aliases and new not in seen:
            seen.add(new)
            new = tree.aliases[new]
        assert new in tree.nodes, f"{old} has no surviving stand-in"
