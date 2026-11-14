"""Compare segmentation approaches against the hand-written reference groupings.

    python3 -m codezoom.evaluate

Scores are boundary precision / recall / F1 (a boundary counts only at the exact
position) and WindowDiff (lower is better; near misses cost less than far ones).
"""
from __future__ import annotations

import json
from pathlib import Path

from . import segment
from .features import Features
from .graph import Tree, load

GOLD = Path(__file__).parent / "gold" / "segments.json"
MODEL = Path(__file__).parent / "gold" / "model_baseline.json"


def window_diff(ref: list[int], hyp: list[int], n: int) -> float:
    k = max(2, round(n / (2 * len(ref))))
    if n <= k:
        return 0.0
    r, h = set(ref) - {0}, set(hyp) - {0}
    bad = 0
    for i in range(n - k):
        window = range(i + 1, i + k + 1)
        bad += sum(b in r for b in window) != sum(b in h for b in window)
    return bad / (n - k)


def score(
    results: dict[str, list[int]], gold: dict[str, list[int]], sizes: dict[str, int]
) -> dict[str, float]:
    tp = fp = fn = 0
    wd = []
    for key, ref in gold.items():
        r, h = set(ref) - {0}, set(results[key]) - {0}
        tp, fp, fn = tp + len(r & h), fp + len(h - r), fn + len(r - h)
        wd.append(window_diff(ref, results[key], sizes[key]))
    p = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * rec / (p + rec) if p + rec else 0.0
    return {
        "precision": p,
        "recall": rec,
        "f1": f1,
        "window_diff": sum(wd) / len(wd),
    }


def approaches(target_k: bool):
    """name -> function(features, gold_k) -> starts. `target_k` gives each method the reference group count."""

    def k_range(n: int, k: int) -> tuple[int, int]:
        return (k, k) if target_k else (2, min(8, n))

    def dp(flow: float, data: float, lexical: float, gamma: float = 1.0):
        def run(f: Features, k: int) -> list[int]:
            lo, hi = k_range(len(f.steps), k)
            return segment.modularity_dp(
                f.affinity(flow, data, lexical), gamma, lo, hi
            )

        return run

    def louvain(f: Features, k: int) -> list[int]:
        return segment.louvain(f.affinity(1, 1, 1))[0]

    def default_k(f: Features, k: int) -> int:
        return k if target_k else segment.group_count(len(f.steps), hi=8)

    out = {
        "uniform length": lambda f, k: segment.uniform(
            len(f.steps), default_k(f, k)
        ),
        "equal statement count": lambda f, k: segment.weight_balanced(
            f.weights, default_k(f, k)
        ),
        "min-cut + balance": lambda f, k: segment.min_cut_dp(
            f.affinity(1, 1, 1), default_k(f, k), f.weights
        ),
        "modularity DP: flow only": dp(1, 0, 0),
        "modularity DP: flow + lexical": dp(1, 0, 1),
        "modularity DP: flow + data": dp(1, 1, 0),
        "modularity DP: all three": dp(1, 1, 1),
        "modularity DP: all, gamma 1.5": dp(1, 1, 1, 1.5),
        "modularity DP: all, gamma 2": dp(1, 1, 1, 2.0),
    }
    if not target_k:
        out["Louvain, unordered (2023)"] = louvain
    return out


def run(
    tree: Tree | None = None, verbose: bool = True
) -> dict[str, dict[str, dict[str, float]]]:
    tree = tree or load()
    gold = {
        k: v
        for k, v in json.loads(GOLD.read_text()).items()
        if not k.startswith("_")
    }
    feats = {key: Features(tree, tree.flow_order(key)) for key in gold}
    sizes = {key: len(f.steps) for key, f in feats.items()}
    report: dict[str, dict[str, dict[str, float]]] = {}
    for target_k in (False, True):
        mode = "group count given" if target_k else "group count free"
        report[mode] = {}
        for name, fn in approaches(target_k).items():
            results = {key: fn(feats[key], len(gold[key])) for key in gold}
            report[mode][name] = score(results, gold, sizes)
        if not target_k and MODEL.exists():
            model = {
                k: sorted(set(v))
                for k, v in json.loads(MODEL.read_text()).items()
                if not k.startswith("_")
            }
            report[mode]["language model (cached answer)"] = score(
                model, gold, sizes
            )
        if verbose:
            print(
                f"\n{mode}  ({len(gold)} charts, {sum(len(v) - 1 for v in gold.values())} reference boundaries)"
            )
            print(
                f"  {'approach':34s} {'P':>5s} {'R':>5s} {'F1':>5s} {'WinDiff':>8s}"
            )
            for name, s in report[mode].items():
                print(
                    f"  {name:34s} {s['precision']:5.2f} {s['recall']:5.2f} {s['f1']:5.2f} {s['window_diff']:8.2f}"
                )
    if verbose:
        breaks = sum(segment.louvain(f.affinity(1, 1, 1))[1] for f in feats.values())
        print(
            f"\nLouvain produced {breaks} communities that are not one consecutive run of steps."
        )
    return report


if __name__ == "__main__":
    run()
