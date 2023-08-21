from __future__ import annotations

import ast
import asyncio
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from langchain.embeddings import OpenAIEmbeddings
from loguru import logger

from codebase_analyzer.parser.callgraph import URI
from codebase_analyzer.parser.deftree import (
    CodeInfo,
    CodeNode,
    NodeType,
    should_split_class_child,
    uri_from_ast,
)
from codebase_analyzer.tools.context import get_code_length
from codebase_analyzer.tools.summary import SummaryBot

_FAKE_RUN = False
_EMBEDDING_INPUT_LIMIT = 8191
_EMBEDDING_DIMENSION = 1536

# TODO: Add language type info.
_FUNCTION_SUMMARY_PROMPT = """
=====
CODE TO SUMMARIZE
=====

{code}

====
REFERENCES
====
Summary of functions called by the above code:

-------------------
URI (type): Summary
-------------------
{summaries}
"""

_CLASS_SUMMARY_PROMPT = """
=====
CODE TO SUMMARIZE
=====

{code}

====
REFERENCES
====
The summaries of its superclasses:

-------------------
URI (type): Summary
-------------------
{summaries}
"""

_JOINED_SUMMARY_PROMPT = """
=====
CONTENTS TO SUMMARIZE
=====
This is a {type} containing the following parts in it:

-------------------
URI (type): Summary
-------------------
{summaries}
"""


def _uri_stem(uri: URI) -> str:
    return uri.split("/.")[-1]


def _join_summaries(
    uris: list[URI], uri2node: dict[URI, CodeNode], before=""
) -> str:
    summaries = []
    for n in [uri2node[u] for u in uris]:
        stem = _uri_stem(n.uri)
        summaries.append(f"{before}{stem} ({n.type}): {n.summary}")
    return "\n".join(summaries) or "No summary found."


def _function_summary_input(node: CodeNode, uri2node: dict[URI, CodeNode]) -> str:
    summaries = _join_summaries(uris=node.calls, uri2node=uri2node, before="")
    return _FUNCTION_SUMMARY_PROMPT.format(code=node.code, summaries=summaries)


def _class_summary_input(node: CodeNode, uri2node: dict[URI, CodeNode]) -> str:
    # node.body will be interpreted as a module. Need to take the class ast out.
    ast_node = ast.parse(node.code).body[0]
    for child_ast in ast_node.body:
        if should_split_class_child(child_ast):
            child_uri = uri_from_ast(
                node=child_ast, parent=node, type=NodeType.CLASS_METHOD
            )
            comment = f"NOTE: Code is omitted here. Summary for it: {uri2node[child_uri].summary}"
            child_ast.body = [ast.Expr(value=ast.Str(s=comment))]
    summaries = _join_summaries(uris=node.superclasses, uri2node=uri2node, before="")
    return _CLASS_SUMMARY_PROMPT.format(
        code=ast.unparse(ast_node), summaries=summaries
    )


def _summary_input(node: CodeNode, uri2node: dict[URI, CodeNode]) -> None:
    """Shorten code of a module by replacing long children code with summaries."""
    # TODO: Add logic to check the length of the input.

    if node.type in (NodeType.STATEMENT, NodeType.ENTRYPOINT):
        return node.code

    if node.type in (NodeType.FUNCTION, NodeType.CLASS_METHOD):
        return _function_summary_input(node, uri2node=uri2node)

    if node.type == NodeType.CLASS:
        return _class_summary_input(node, uri2node=uri2node)

    if node.type in (NodeType.MODULE, NodeType.PACKAGE):
        summaries = _join_summaries(uris=node.children, uri2node=uri2node)
        return _JOINED_SUMMARY_PROMPT.format(type=node.type, summaries=summaries)


def _embedding_input(
    node: CodeNode, uri2node: dict[URI, CodeNode], limit=_EMBEDDING_INPUT_LIMIT
) -> None:
    """Simplify code of Modules and Classes in case length exceedes 8k token limit."""
    # Concatenate summary for packages.
    if node.code is None:
        assert node.type == NodeType.PACKAGE
        return _join_summaries(uris=node.children, uri2node=uri2node)

    # Use raw code if short enough.
    if node.code and node.code_length <= limit:
        assert node.code_length == get_code_length(node.code)  # For debugging
        return node.code

    # Use concatenated summaries if code is too long.
    # NOTE: This won't ensure the input is short enough, but better than nothing.
    return _join_summaries(uris=node.children, uri2node=uri2node)

    # TODO: Should we keep the raw code as much as possible?
    # if node.type == NodeType.MODULE:
    #     _shorten_module_code(node, uri2node=uri2node)
    # elif node.type == NodeType.CLASS:
    #     _shorten_class_code(node, uri2node=uri2node)


async def apopulate_summary(
    node: CodeNode,
    uri2node: dict[URI, CodeNode],
    summary_bot: SummaryBot,
    update_existing: bool,
) -> None:
    logger.info(f"generate summary for {node.uri}")

    if update_existing and node.summary is not None:
        return
    elif _FAKE_RUN:
        import random

        t = random.uniform(0.0, 3.0)
        await asyncio.sleep(t)
        if t >= 2.8:
            raise asyncio.TimeoutError("timeout")
        node.summary = f"Summary for {node.uri}"
    else:
        node.summary = await summary_bot.asummarize_code(
            code=_summary_input(node, uri2node=uri2node)
        )


async def apopulate_embedding(
    node: CodeNode,
    uri2node: dict[URI, CodeNode],
    embeddings: OpenAIEmbeddings,
    update_existing: bool,
) -> None:
    logger.info(f"generate embedding for {node.uri}")
    if update_existing and node.embedding is not None:
        return
    elif _FAKE_RUN:
        import random

        t = random.uniform(0.0, 3.0)
        await asyncio.sleep(t)
        if t >= 2.8:
            raise asyncio.TimeoutError("timeout")
        node.embedding = [0.1, 0.2, 0.3]

    else:
        node.embedding = await embeddings.aembed_query(
            _embedding_input(node, uri2node=uri2node)
        )


def _handle_error(
    error: Exception,
    node: CodeNode,
    failures: dict[URI, int],
    max_failures: int,
    timeout: int,
    done: dict[URI, int],
    ready: set[CodeNode],
) -> None:
    """Handle error when processing a node.

    TODO: Currently we raise the error when a node fails too many times, which
    also makes the whole code tree fail. Later we might want to finish the sub
    tree we can finish and make the user can resume from a wip tree."""
    if type(error) is asyncio.TimeoutError:
        logger.error(
            f"Processing node {node.uri} timed out after {timeout}s, will retry."
        )
    failures[node.uri] += 1
    if failures[node.uri] < max_failures:
        ready.add(node.uri)
    else:
        logger.exception(
            f"Node {node.uri} failed {failures[node.uri]} times. Abort it by setting "
            "error info to the node."
        )
        done[node.uri] = -1
        if node.summary is None:
            node.summary = "Failed to generate summary due to timeout error."
        if node.embedding is None:
            node.embedding = [0.0] * _EMBEDDING_DIMENSION


def _update_states(
    node: CodeNode,
    ready: set[URI],
    done: dict[URI, int],
    waiting: dict[URI, set[URI]],
) -> None:
    """Update states after a node is processed successfully.
    Will update `ready`, `summaries` and `waiting` inplace."""
    done[node.uri] += 1
    upstream_uris = set([node.parent] + node.called_by + node.subclasses)
    upstream_uris.discard(None)  # parent could be None
    upstream_uris.discard(node.uri)  # in case recursive calls
    for upstream_uri in upstream_uris:
        # Uses remove to check if the node is in the waiting list.
        waiting[upstream_uri].remove(node.uri)
        if len(waiting[upstream_uri]) == 0:
            ready.add(upstream_uri)


def _check_state(
    node: CodeNode,
    waiting: dict[URI, set[URI]],
    ready: set[URI],
    uri2node: dict[URI, CodeNode],
) -> None:
    """Recursively collects all nodes' downstream nodes and puts nodes without
    any downstream into the ready list."""

    downstream = set(node.children + node.superclasses + node.calls)

    # NOTE: For preventing dead lock of recursive calls.
    downstream.discard(node.uri)
    waiting[node.uri].update(downstream)
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
    waiting: dict[URI, set[URI]] = defaultdict(set)
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
    update_existing: bool = False,
) -> None:
    """Populate summary and embedding for all nodes in the code tree."""
    summary_bot = SummaryBot()
    embeddings = OpenAIEmbeddings()
    condition = asyncio.Condition()

    waiting, ready = check_state(root=root, uri2node=uri2node)
    total = len(waiting)
    worker_num = min(worker_num, total)
    failures = Counter()
    done = Counter()

    async def process_node(node: CodeNode) -> None:
        try:
            await asyncio.gather(
                apopulate_embedding(
                    node=node,
                    uri2node=uri2node,
                    embeddings=embeddings,
                    update_existing=update_existing,
                ),
                apopulate_summary(
                    node=node,
                    uri2node=uri2node,
                    summary_bot=summary_bot,
                    update_existing=update_existing,
                ),
            )
        except Exception as e:
            _handle_error(
                error=e,
                node=node,
                failures=failures,
                max_failures=max_failures,
                timeout=timeout,
                ready=ready,
                done=done,
            )
        else:
            _update_states(
                node=node,
                ready=ready,
                done=done,
                waiting=waiting,
            )

        # Notify all workers to check updated state.
        async with condition:
            condition.notify_all()

    async def worker():
        while True:
            async with condition:
                await condition.wait_for(lambda: ready or len(done) >= total)
                if len(done) >= total:
                    break
                node = uri2node[ready.pop()]
            await process_node(node)
            logger.info(f"Completed {len(done)}/{total}.")
            logger.debug(f"{len(ready)=}")

    workers = [asyncio.create_task(worker()) for _ in range(worker_num)]
    await asyncio.gather(*workers)
    return done


def check_summaries(
    nodes: dict[URI, CodeNode], block_size: int, done: dict[URI, int]
) -> None:
    """Some sanity check on the generated code info to give insights to developers."""
    for n in nodes.values():
        if n.code is None:
            continue
        length = get_code_length(n.code)
        if length != n.code_length:
            logger.warning(
                f"Code length {length} != {n.code_length} in CodeNode {n.uri}."
            )
        if length > block_size:
            logger.warning(f"Block has length {length} > {block_size}.")

    summary = "\n".join([n.summary for n in nodes.values() if n.summary is not None])
    raw_code = "\n".join([n.code for n in nodes.values() if n.code is not None])
    logger.info(
        f"\n===== Code Info Summary =====\n"
        f"Extracted code nodes num: {len(nodes)}\n"
        f"Original code length: {len(raw_code)}\n"
        f"Extracted summary length: {len(summary)}\n"
        f"Compression ratio: {len(raw_code) / len(summary):.2f}\n"
    )
    logger.debug(
        f"Nodes that runs more than once: {[(i, c) for i, c in done.items() if c !=1]}"
    )


# TODO: Centralize all the configs.
def generate_summary_embedding(
    codeinfo: CodeInfo,
    block_size: int = 1000,
    update_existing: bool = False,
) -> CodeInfo:
    """Extracts code info from a file.

    Args:
        filepath: Full path to the file.
        block_size: The maximum number of tokens in a code block.
        skip_token_num: If the lenth of nested child code is shorter than this, it won't be splitted.

    Returns:
        A dataframe of code info, each row is a code block. Check `CodeInfo` for columns.
    """

    done = asyncio.run(
        apopulate_summary_and_embedding(
            root=codeinfo.root_node,
            uri2node=codeinfo.nodes,
            update_existing=update_existing,
        )
    )
    check_summaries(codeinfo.nodes, block_size=block_size, done=done)
    return codeinfo
