"""Grouping decisions that need a language model, kept in a cache file.

The rebalancing pass asks one question per over-full chart: "which consecutive steps
form one job, and what would you call each job?". Answers live in
codezoom/cache/groupings.json, keyed by the chart's steps, so a run is deterministic
and needs no key. A chart with no cached answer falls back to the dynamic-programming
segmenter and its request is written to codezoom/cache/pending.json.

Filling the cache:
    * `python3 -m codezoom.export --ask` sends pending requests to the Anthropic API
      (needs the `anthropic` package and ANTHROPIC_API_KEY), or
    * answer pending.json by any other means and merge with `--merge answers.json`.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .graph import Tree, short_fn

CACHE = Path(__file__).parent / "cache" / "groupings.json"
PENDING = Path(__file__).parent / "cache" / "pending.json"

INSTRUCTIONS = """Each chart below is a numbered list of steps from a Python program, in execution order. \
Each step has a one-line description, its statement count in brackets, and the first lines of its code. \
"Inside" says where the chart sits in the program.

For each chart, group the steps into consecutive runs that each do one job a programmer would name. \
Rules: groups are consecutive steps; every step belongs to exactly one group; use at least the chart's "min groups" \
and at most its "max groups"; a single step may be its own group when it is a job of its own, and a step with a large \
statement count usually is. Judge by what the code does. "Min groups" is 3 unless the chart says otherwise.

When the steps come from more than one function (each step then says which), the steps of one called \
function belong together: keep them in one group named after what that call achieves, and do not mix them \
with the caller's steps. Avoid a group of just two small steps unless they are clearly one job. \
Titles and summaries speak to a developer new to the program: say what the group achieves for the agent \
or the user, and be exact about conditions (read the steps' labels and code).

Answer with one JSON object. Keys are the chart keys. Each value is the list of groups in order: \
{"start": <index of the group's first step>, "title": "<2 to 5 words, sentence case, no trailing period>", \
"summary": "<one plain sentence under 20 words saying what the group does>"}. The first group starts at 0."""


NAMING = """Each entry under "names" is a run of consecutive steps from a Python program that will be shown as one \
block in a diagram. Name each block. Answer with one JSON object: keys are the entry keys, each value is \
{"title": "<2 to 5 words, sentence case, no trailing period, the job in the program's terms>", \
"summary": "<one plain sentence under 20 words saying what the block does>"}."""


def key_of(steps: list[str], limit: int) -> str:
    # v2: requests carry the step's function and the relabelled steps
    return hashlib.sha1(("|".join(steps) + f"#{limit}#v2").encode()).hexdigest()[:16]


def render(
    tree: Tree,
    scope: str,
    steps: list[str],
    limit: int,
    cap: int | None = None,
    least: int | None = None,
) -> str:
    trail = [tree[a].title for a in tree.lineage(scope) if tree[a].title]
    lines = [
        f"### chart {key_of(steps, limit)}",
        f"Inside: {' › '.join(trail) or 'Program'}",
        f"Max groups: {limit}",
    ]
    if least and least != 3:
        lines.append(f"Min groups: {least}")
    if cap:
        lines.append(
            f"Largest group: the statement counts of a group of two or more steps must add up to at most {cap}"
        )
    fns = {tree[s].fn for s in steps}
    for i, s in enumerate(steps):
        n = tree[s]
        code = (n.code or "").split("\n")
        head = "\n      ".join(code[:4]) + (" …" if len(code) > 4 else "")
        what = f"{n.title}: {n.label}" if n.kind == "group" else (n.label or n.title)
        where = f" (in {short_fn(n.fn)})" if len(fns) > 1 else ""
        lines.append(f"  {i}. [{tree.weight(s)}]{where} {what}\n      {head}")
    return "\n".join(lines)


class Oracle:
    def __init__(self, use_cache: bool = True):
        self.cache: dict = (
            json.loads(CACHE.read_text()) if use_cache and CACHE.exists() else {}
        )
        self.pending: dict[str, str] = {}
        self.pending_names: dict[str, str] = {}
        self.hits = 0
        self.used: set[str] = set()

    def grouping(
        self,
        tree: Tree,
        scope: str,
        steps: list[str],
        limit: int,
        cap: int | None = None,
        least: int | None = None,
    ) -> list[dict] | None:
        key = key_of(steps, limit)
        groups = self.cache.get(key)
        if groups is None:
            self.pending[key] = render(tree, scope, steps, limit, cap, least)
            return None
        starts = [g.get("start") for g in groups]
        ok = (
            starts
            and starts[0] == 0
            and starts == sorted(set(starts))
            and all(isinstance(s, int) and 0 <= s < len(steps) for s in starts)
            and len(starts) <= limit
        )
        if not ok:
            return None
        self.hits += 1
        self.used.add(key)
        return groups

    def name(
        self, tree: Tree, scope: str, members: list[str]
    ) -> tuple[str, str] | None:
        """Title and summary for a group the segmenter made."""
        key = "n" + key_of(members, 0)
        hit = self.cache.get(key)
        if isinstance(hit, dict) and hit.get("title") and hit.get("summary"):
            self.used.add(key)
            return hit["title"], hit["summary"]
        self.pending_names[key] = render(tree, scope, members, 0).split("\n", 3)[-1]
        return None

    def flush(self) -> None:
        if self.pending or self.pending_names:
            body = {
                "instructions": INSTRUCTIONS,
                "charts": self.pending,
                "naming": NAMING,
                "names": self.pending_names,
            }
            PENDING.write_text(json.dumps(body, indent=1) + "\n")
        elif PENDING.exists():
            PENDING.unlink()


def prune(used: set[str]) -> int:
    """Drop cached answers no chart asked for (left over from earlier prompts)."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    kept = {k: v for k, v in cache.items() if k in used}
    CACHE.write_text(json.dumps(kept, indent=1, sort_keys=True) + "\n")
    return len(cache) - len(kept)


def merge(answers: dict[str, list[dict]]) -> int:
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    cache.update(answers)
    CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True) + "\n")
    return len(answers)


def ask_api(model: str = "claude-haiku-5-5") -> int:
    """Answer pending requests with the Anthropic API and merge them into the cache."""
    import anthropic  # optional dependency

    pending = json.loads(PENDING.read_text())
    charts = list(pending["charts"].values())
    client = anthropic.Anthropic()
    answers: dict[str, list[dict]] = {}
    for at in range(0, len(charts), 8):
        prompt = pending["instructions"] + "\n\n" + "\n\n".join(charts[at : at + 8])
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        answers.update(json.loads(text[text.index("{") : text.rindex("}") + 1]))
    return merge(answers)
