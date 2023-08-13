from __future__ import annotations

import ast
import asyncio
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from langchain.embeddings import OpenAIEmbeddings
from loguru import logger

from codebase_analyzer.parser.deftree import CodeInfo, CodeNode
from codebase_analyzer.parser.schema import CodeInfoLevel
from codebase_analyzer.tools.context import get_code_length
from codebase_analyzer.tools.summary import SummaryBot


def _prefix_name(node: CodeNode, parent: CodeNode, level: int) -> str:
    """For nested class or function, prefix its name with its parent's name.
    E.g. method `foo` in class `A`'s name is `A.foo`"""
    name = node.ast[0].name
    if level == CodeInfoLevel.NESTED_CHILD:
        name = f"{parent.ast[0].name}.{name}"
    return name


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
            skeleton_code=node.info.code, children_summary=children_summary
        )
    else:
        code = node.info.code
    return code


async def apopulate_summary(node: CodeNode, summary_bot: SummaryBot) -> None:
    node.info.summary = await summary_bot.asummarize_code(code=_construct_code(node))


async def apopulate_embedding(node: CodeNode, embeddings: OpenAIEmbeddings) -> None:
    node.info.embedding = await embeddings.aembed_query(node.info.code)


def _handle_error(
    error: Exception,
    node: CodeNode,
    failures: dict[int],
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
    ready: set,
    code_info: list[CodeInfo],
    todo_children: dict,
    child_to_parent: dict,
) -> None:
    """Update states after a node is processed successfully.
    Will update `ready`, `code_info` and `todo_children` inplace."""
    code_info.append(node.info)
    parent = child_to_parent.get(node)
    if parent is not None:
        todo_children[parent] -= 1
        if todo_children[parent] == 0:
            ready.add(parent)


def _count_children(
    node: CodeNode,
    todo_children: dict[CodeNode, int],
    child_to_parent: dict[CodeNode, CodeNode],
) -> None:
    """Recursively counts how many children a node has and build connections
    from children to parents."""
    todo_children[node] += len(node.children)
    for child in node.children:
        child_to_parent[child] = node
        _count_children(
            node=child,
            todo_children=todo_children,
            child_to_parent=child_to_parent,
        )


async def apopulate_summary_and_embedding(
    root: CodeNode, worker_num: int = 20, timeout: int = 180, max_failures: int = 5
) -> None:
    """Populate summary and embedding for all nodes in the code tree."""
    summary_bot = SummaryBot()
    embeddings = OpenAIEmbeddings()
    todo_children = defaultdict(int)
    child_to_parent = {}

    _count_children(
        node=root, todo_children=todo_children, child_to_parent=child_to_parent
    )

    condition = asyncio.Condition()
    ready = {node for node, count in todo_children.items() if count == 0}
    total = len(todo_children)
    failures = Counter()
    code_info = []

    async def process_node(node):
        # nonlocal code_info
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
                code_info=code_info,
                child_to_parent=child_to_parent,
                todo_children=todo_children,
            )

        # Notify all workers to check updated state.
        async with condition:
            condition.notify_all()

    async def worker():
        while True:
            async with condition:
                await condition.wait_for(lambda: ready or len(code_info) >= total)
                if len(code_info) >= total:
                    break
                node = ready.pop()
            await process_node(node)
            logger.info(f"Completed {len(code_info)}/{total}.")

    workers = [asyncio.create_task(worker()) for _ in range(worker_num)]
    await asyncio.gather(*workers)
    return pd.DataFrame(c.dict() for c in code_info).sort_values("index")


def check_code_info(code_info: pd.DataFrame, block_size: int) -> None:
    """Some sanity check on the generated code info to give insights to developers."""
    for name, length in zip(code_info.name, code_info.length_in_token):
        if length > block_size:
            logger.warning(f"Block {name} has length {length} > {block_size}.")

    summary = "\n".join(s for s in code_info.summary)
    raw_code = "\n".join(s for s in code_info.code)
    logger.info(
        f"\n===== Code Info Summary =====\n"
        f"Original Code length: {len(raw_code)}\n"
        f"Extracted block num: {len(code_info)}\n"
        f"Extracted Code length: {len(summary)}\n"
    )


# TODO: Centralize all the configs.
def extract_code_info(
    root_node: CodeNode,
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

    code_info = asyncio.run(apopulate_summary_and_embedding(root_node))
    check_code_info(code_info, block_size=block_size)
    return code_info


def load_cached_code_info(path: Path) -> pd.DataFrame:
    """Load cached codebase info from the given csv file."""
    code_info = pd.read_csv(path)
    logger.info(f"Loaded codebase info from {path}")

    # TODO: Use format supporting storing the embeddings instead of CSV
    # TODO: Create single source of true for names of the columns, mabye use
    # langchain.Document will solve the problem automatically.
    code_info["embedding"] = code_info["embedding"].apply(ast.literal_eval)
    return code_info
