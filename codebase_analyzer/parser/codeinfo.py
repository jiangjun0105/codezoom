from __future__ import annotations

import ast
import asyncio
from collections import defaultdict
from pathlib import Path

import pandas as pd
from langchain.embeddings import OpenAIEmbeddings
from loguru import logger

from codebase_analyzer.common.credentials import get_api_key
from codebase_analyzer.parser.ast_visitor import CodeExtractor
from codebase_analyzer.parser.schema import CodeInfo, CodeInfoLevel, CodeNode
from codebase_analyzer.tools.context import get_code_length
from codebase_analyzer.tools.summary import SummaryBot


def _prefix_name(node: CodeNode, parent: CodeNode, level: int) -> str:
    """For nested class or function, prefix its name with its parent's name.
    E.g. method `foo` in class `A`'s name is `A.foo`"""
    name = node.ast[0].name
    if level == CodeInfoLevel.NESTED_CHILD:
        name = f"{parent.ast[0].name}.{name}"
    return name


def _omit_children_code(node: CodeNode) -> str:
    """For long class or function, omit its children code for brevity."""
    for child in node.children:
        comment = f"NOTE: function body is ommited here but can be found in block `{child.info.name}`."
        child.ast[0].body = [ast.Expr(value=ast.Str(s=comment))]
    return ast.unparse(node.ast[0])


def code_info_from_ast(
    node: CodeNode, level: CodeInfoLevel, index: int, parent: CodeNode
) -> None:
    """Generates code info from the AST. Summary and embedding are not populated."""

    if not node.children:
        if node.isolated:
            # Full class or function
            code = ast.unparse(node.ast[0])
            name = _prefix_name(node=node, parent=parent, level=level)
        else:
            # Group of statements
            code = "\n".join(ast.unparse(n) for n in node.ast)
            name = f"code_block_of_level_{level}_index_{index}"
    else:
        assert len(node.ast) == 1
        assert node.isolated is True
        if level != CodeInfoLevel.MODULE:
            # Splitted class or function
            name = node.ast[0].name
            code = _omit_children_code(node=node)
        else:
            # Module
            name = "module_structure_overview"
            code = "\n\n".join(n.info.name for n in node.children)

    node.info = CodeInfo(
        name=name,
        code=code,
        length_in_token=get_code_length(code),
        level=level,
    )


def generate_code_info(
    node: CodeNode,
    level: CodeInfoLevel = CodeInfoLevel.MODULE,
    index: int = 0,
    parent: CodeNode = None,
) -> CodeInfo:
    """Recursively generate code info from code tree. A node's info can be
    generated only after all its children's info are generated.
    TODO: This way we cannot do lazy generation for a large codebase."""

    for i, child in enumerate(node.children):
        generate_code_info(child, level=level + 1, index=i, parent=node)
    code_info_from_ast(node, level=level, index=index, parent=parent)


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


async def apopulate_summary_and_embedding(
    root: CodeNode, worker_num: int = 20
) -> None:
    todo_children = defaultdict(int)
    child_to_parent = {}
    summary_bot = SummaryBot()
    embeddings = OpenAIEmbeddings(openai_api_key=get_api_key())

    def count_children(node):
        todo_children[node] += len(node.children)
        for child in node.children:
            child_to_parent[child] = node
            count_children(child)

    count_children(root)

    condition = asyncio.Condition()
    ready = {node for node, count in todo_children.items() if count == 0}
    total = len(todo_children)
    code_info = []

    async def process_node(node):
        nonlocal code_info
        await asyncio.gather(
            apopulate_embedding(node, embeddings),
            apopulate_summary(node, summary_bot),
        )
        code_info.append(node.info)
        parent = child_to_parent.get(node)
        if parent is not None:
            todo_children[parent] -= 1
            if todo_children[parent] == 0:
                ready.add(parent)
        async with condition:
            # Notify all workers to check updated state.
            condition.notify_all()

    async def worker():
        while True:
            logger.info(f"Completed {len(code_info)}/{total}.")
            async with condition:
                await condition.wait_for(lambda: ready or len(code_info) >= total)
                if len(code_info) >= total:
                    break
                node = ready.pop()
            await process_node(node)

    workers = [asyncio.create_task(worker()) for _ in range(worker_num)]
    await asyncio.gather(*workers)
    return pd.DataFrame(c.dict() for c in code_info)


def check_code_info(code_info: pd.DataFrame, block_size: int, raw_code: str) -> None:
    """Some sanity check on the generated code info to give insights to developers."""
    for name, length in zip(code_info.name, code_info.length_in_token):
        if length > block_size:
            logger.warning(f"Block {name} has length {length} > {block_size}.")

    summary = "\n".join(s for s in code_info.summary)
    logger.info(
        f"\n===== Code Info Summary =====\n"
        f"Original Code length: {len(raw_code)}\n"
        f"Extracted block num: {len(code_info)}\n"
        f"Extracted Code length: {len(summary)}\n"
    )


# TODO: Centralize all the configs.
def extract_code_info(
    filepath: Path, block_size: int = 1000, skip_token_num: int = 20
) -> pd.DataFrame:
    """Extracts code info from a file.

    Args:
        filepath: Full path to the file.
        block_size: The maximum number of tokens in a code block.
        skip_token_num: If the lenth of nested child code is shorter than this, it won't be splitted.

    Returns:
        A dataframe of code info, each row is a code block. Check `CodeInfo` for columns.
    """
    code = filepath.expanduser().read_text()
    code_tree = CodeExtractor.generate_code_tree(
        code=code,
        block_size=block_size,
        skip_token_num=skip_token_num,
    )
    generate_code_info(code_tree)
    code_info = asyncio.run(apopulate_summary_and_embedding(code_tree))
    check_code_info(code_info, block_size=block_size, raw_code=code)
    return code_info


def load_cached_code_info(path: Path) -> pd.DataFrame:
    """Load cached codebase info from the given csv file."""
    code_info = pd.read_csv(path)
    logger.info(f"Loaded codebase info from {path}")

    # TODO: Use format supporting storing the embeddings instead of CSV
    # TODO: Create single source of true for names of the columns, mabye use langchain.Document
    code_info["embedding"] = code_info["embedding"].apply(ast.literal_eval)
    return code_info
