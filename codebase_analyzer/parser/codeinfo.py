from __future__ import annotations

import ast
import asyncio
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from langchain.embeddings import OpenAIEmbeddings
from loguru import logger

from codebase_analyzer.parser.callgraph import URI
from codebase_analyzer.parser.deftree import CodeNode
from codebase_analyzer.tools.context import get_code_length
from codebase_analyzer.tools.summary import SummaryBot

_OMIT_CODE_PROMPT = """Note to AI bot: some blocks are ommited in the skeleton but explained in `summary of ommited blocks`
Please combine both to reconstruct the original code in your mind and the give a compresive summary of it."

=====
Skeleton code:

{skeleton_code}

=====
Summary of ommited blocks:

{children_summary}
"""


def _construct_code(node: CodeNode) -> str:
    # TODO: Use children summary to generate summary for the parent.
    if node.children:
        children_summary = "\n".join(
            f"{c.info.name}: {c.info.summary}" for c in node.children
        )
        code = _OMIT_CODE_PROMPT.format(
            skeleton_code=node.code, children_summary=children_summary
        )
    else:
        code = node.code
    return code


async def apopulate_summary(node: CodeNode, summary_bot: SummaryBot) -> None:
    # node.summary = await summary_bot.asummarize_code(code=_construct_code(node))
    print(f"generate summary for {node.uri}")
    node.summary = f"summary for {node.uri}"


async def apopulate_embedding(node: CodeNode, embeddings: OpenAIEmbeddings) -> None:
    # node.embedding = await embeddings.aembed_query(node.code)
    print(f"generate embedding for {node.uri}")
    node.embedding = [1, 2, 3]


def _handle_error(
    error: Exception,
    node: CodeNode,
    failures: dict[CodeNode, int],
    max_failures: int,
    timeout: int,
    ready: set[CodeNode],
) -> None:
    """Handle error when processing a node.

    TODO: Currently we raise the error when a node fails too many times, which
    also makes the whole code tree fail. Later we might want to finish the sub
    tree we can finish and make the user can resume from a wip tree."""
    if type(error) is asyncio.TimeoutError:
        logger.error(
            f"Processing node {node} timed out after {timeout}s, will retry."
        )
    failures[node] += 1
    if failures[node] < max_failures:
        ready.add(node)
    else:
        logger.exception(
            f"Node {node} failed {failures[node]} times. Abort as we cannot "
            "finish processing the whole code tree anyway."
        )
        raise error


def _update_states(
    node: CodeNode,
    ready: set[URI],
    summaries: list[str],
    waiting: dict[URI, int],
) -> None:
    """Update states after a node is processed successfully.
    Will update `ready`, `summaries` and `waiting` inplace."""
    summaries.append(node.summary)
    for upstream_uri in [node.parent] + node.called_by + node.subclasses:
        if upstream_uri is None:
            continue
        waiting[upstream_uri] -= 1
        assert waiting[upstream_uri] >= 0
        if waiting[upstream_uri] == 0:
            ready.add(upstream_uri)


def _check_state(
    node: CodeNode,
    waiting: dict[URI, int],
    ready: set[URI],
    uri2node: dict[URI, CodeNode],
) -> None:
    """Recursively counts how many children a node has and build connections
    from children to parents."""
    downstream = set(node.children + node.superclasses + node.calls)
    waiting[node.uri] += len(downstream)
    if not downstream:
        ready.add(node.uri)

    for child_uri in node.children:
        child = uri2node[child_uri]
        _check_state(
            node=child,
            waiting=waiting,
            ready=ready,
            uri2node=uri2node,
        )


def check_state(root: CodeNode, uri2node: dict[URI, CodeNode]) -> tuple[dict, dict]:
    waiting: dict[URI, int] = defaultdict(int)
    ready: set[URI] = set()

    _check_state(node=root, uri2node=uri2node, waiting=waiting, ready=ready)

    assert len(waiting) == len(uri2node)
    return waiting, ready


async def apopulate_summary_and_embedding(
    root: CodeNode,
    uri2node: dict[URI, CodeNode],
    worker_num: int = 20,
    timeout: int = 180,
    max_failures: int = 5,
) -> None:
    """Populate summary and embedding for all nodes in the code tree."""
    summary_bot = SummaryBot()
    embeddings = OpenAIEmbeddings()
    condition = asyncio.Condition()

    waiting, ready = check_state(root=root, uri2node=uri2node)
    total = len(waiting)
    failures = Counter()
    summaries = []

    async def process_node(node: CodeNode) -> None:
        # nonlocal summaries
        try:
            await asyncio.gather(
                apopulate_embedding(node, embeddings),
                apopulate_summary(node, summary_bot),
            )
        except Exception as e:
            _handle_error(
                error=e,
                node=node,
                failures=failures,
                max_failures=max_failures,
                timeout=timeout,
                ready=ready,
            )
        else:
            _update_states(
                node=node,
                ready=ready,
                summaries=summaries,
                waiting=waiting,
            )

        # Notify all workers to check updated state.
        async with condition:
            condition.notify_all()

    async def worker():
        while True:
            async with condition:
                await condition.wait_for(lambda: ready or len(summaries) >= total)
                if len(summaries) >= total:
                    break
                node = uri2node[ready.pop()]
            await process_node(node)
            logger.info(f"Completed {len(summaries)}/{total}.")

    workers = [asyncio.create_task(worker()) for _ in range(worker_num)]
    await asyncio.gather(*workers)
    return summaries


def check_summaries(summaries: list[str], block_size: int) -> None:
    """Some sanity check on the generated code info to give insights to developers."""
    for s in summaries:
        length = get_code_length(s)
        if length > block_size:
            logger.warning(f"Block has length {length} > {block_size}.")

    summary = "\n".join(s for s in summaries)
    # raw_code = "\n".join(s for s in summaries)
    logger.info(
        f"\n===== Code Info Summary =====\n"
        # f"Original Code length: {len(raw_code)}\n"
        f"Extracted block num: {len(summaries)}\n"
        f"Extracted Code length: {len(summary)}\n"
    )


# TODO: Centralize all the configs.
def generate_summary_embedding(
    root: CodeNode,
    uri2node: dict[URI, CodeNode],
    block_size: int = 1000,
) -> pd.DataFrame:
    """Extracts code info from a file.

    Args:
        filepath: Full path to the file.
        block_size: The maximum number of tokens in a code block.
        skip_token_num: If the lenth of nested child code is shorter than this, it won't be splitted.

    Returns:
        A dataframe of code info, each row is a code block. Check `CodeInfo` for columns.
    """

    summaries = asyncio.run(
        apopulate_summary_and_embedding(root=root, uri2node=uri2node)
    )
    check_summaries(summaries, block_size=block_size)
    return summaries
