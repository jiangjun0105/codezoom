"""Ways to cut an ordered list of steps into consecutive groups.

Every function returns the sorted start indices of the groups, always beginning with 0.
"""
from __future__ import annotations

Matrix = list[list[float]]


def uniform(n: int, k: int) -> list[int]:
    """Baseline: k groups of equal length."""
    k = max(1, min(k, n))
    return sorted({round(i * n / k) for i in range(k)})


def weight_balanced(weights: list[int], k: int) -> list[int]:
    """Baseline: k groups of roughly equal statement count."""
    total, starts, acc = sum(weights), [0], 0.0
    for i, w in enumerate(weights[:-1]):
        acc += w
        if len(starts) < k and acc >= total * len(starts) / k:
            starts.append(i + 1)
    return starts


def modularity_dp(
    a: Matrix,
    gamma: float = 1.0,
    kmin: int = 1,
    kmax: int | None = None,
    can_cut: list[bool] | None = None,
) -> list[int]:
    """Contiguous segmentation that maximises modularity, solved exactly by dynamic programming.

    Modularity of a partition is the sum over groups of  in(g)/m - gamma * (deg(g)/2m)^2.
    Louvain maximises the same quantity greedily over arbitrary partitions; here groups
    must be consecutive runs, which makes the optimum computable and keeps execution
    order intact. `can_cut[i]` says whether a group may start at step i.
    """
    n = len(a)
    if n == 0:
        return []
    kmax = min(kmax or n, n)
    kmin = min(kmin, kmax)
    deg = [sum(row) for row in a]
    two_m = sum(deg) or 1.0
    # inside[i][j]: total weight of pairs within steps i..j-1
    inside = [[0.0] * (n + 1) for _ in range(n + 1)]
    for i in range(n):
        run = 0.0
        for j in range(i + 1, n + 1):
            run += sum(a[j - 1][i : j - 1])
            inside[i][j] = run
    prefix = [0.0]
    for d in deg:
        prefix.append(prefix[-1] + d)

    def gain(i: int, j: int) -> float:
        d = prefix[j] - prefix[i]
        return 2 * inside[i][j] / two_m - gamma * (d / two_m) ** 2

    ok = can_cut or [True] * n
    neg = float("-inf")
    best = [[neg] * (kmax + 1) for _ in range(n + 1)]
    back = [[0] * (kmax + 1) for _ in range(n + 1)]
    best[0][0] = 0.0
    for j in range(1, n + 1):
        for k in range(1, min(j, kmax) + 1):
            for i in range(k - 1, j):
                if best[i][k - 1] == neg or (i > 0 and not ok[i]):
                    continue
                score = best[i][k - 1] + gain(i, j)
                if score > best[j][k]:
                    best[j][k], back[j][k] = score, i
    feasible = [k for k in range(kmin, kmax + 1) if best[n][k] > neg]
    if not feasible:
        feasible = [k for k in range(1, kmax + 1) if best[n][k] > neg]
    k = max(feasible, key=lambda k: best[n][k])
    starts, j = [], n
    while k > 0:
        j = back[j][k]
        starts.append(j)
        k -= 1
    return sorted(starts)


def min_cut_dp(
    a: Matrix,
    k: int,
    weights: list[int],
    balance: float = 0.5,
    valid: list[list[bool]] | None = None,
) -> list[int]:
    """k groups that minimise the affinity crossing each cut, plus a penalty for uneven statement counts.

    `valid[i][j]` says whether steps i..j-1 may form one group (see retree.sese). When
    no partition into k valid groups exists, k grows until one does.
    """
    n = len(a)
    k = max(1, min(k, n))
    total = sum(weights) or 1
    cross = [0.0] * (n + 1)  # affinity between steps before i and steps from i on
    for i in range(1, n):
        cross[i] = sum(a[p][q] for p in range(i) for q in range(i, n))
    scale = max(cross) or 1.0
    wp = [0]
    for w in weights:
        wp.append(wp[-1] + w)

    inf = float("inf")
    while True:

        def cost(i: int, j: int) -> float:
            share = (wp[j] - wp[i]) / total
            return (cross[i] / scale if i else 0.0) + balance * k * (
                share - 1 / k
            ) ** 2

        best = [[inf] * (k + 1) for _ in range(n + 1)]
        back = [[0] * (k + 1) for _ in range(n + 1)]
        best[0][0] = 0.0
        for j in range(1, n + 1):
            for g in range(1, min(j, k) + 1):
                for i in range(g - 1, j):
                    if best[i][g - 1] == inf or (
                        valid is not None and j - i > 1 and not valid[i][j]
                    ):
                        continue
                    c = best[i][g - 1] + cost(i, j)
                    if c < best[j][g]:
                        best[j][g], back[j][g] = c, i
        if best[n][k] < inf or k >= n:
            break
        k += 1
    starts, j, g = [], n, k
    while g > 0:
        j = back[j][g]
        starts.append(j)
        g -= 1
    return sorted(starts)


def group_count(n: int, lo: int = 3, hi: int = 7) -> int:
    """How many groups to aim for when a chart has n steps: about one per 2.3 steps, within [lo, hi]."""
    return max(min(lo, n), min(hi, round(n / 2.3)))


def louvain(a: Matrix, gamma: float = 1.0, seed: int = 0) -> tuple[list[int], int]:
    """The 2023 approach: Louvain communities on the same graph, with no ordering constraint.

    Returns (starts, breaks). A group starts wherever the community changes along the
    execution order; `breaks` counts communities that are not one consecutive run.
    """
    import networkx as nx

    n = len(a)
    g = nx.Graph()
    g.add_nodes_from(range(n))
    for i in range(n):
        for j in range(i + 1, n):
            if a[i][j] > 0:
                g.add_edge(i, j, weight=a[i][j])
    label = {}
    for c, members in enumerate(
        nx.community.louvain_communities(
            g, weight="weight", resolution=gamma, seed=seed
        )
    ):
        for m in members:
            label[m] = c
    starts = [0] + [i for i in range(1, n) if label[i] != label[i - 1]]
    return starts, len(starts) - len(set(label.values()))
