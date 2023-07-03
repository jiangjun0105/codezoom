from __future__ import annotations

import ast
from enum import Enum

import pandas as pd
from langchain.embeddings import OpenAIEmbeddings
from loguru import logger
from pydantic import BaseModel, Field

from codebase_analyzer.common.credentials import get_api_key
from codebase_analyzer.common.pydantic import AllowArbitraryTypeConfig
from codebase_analyzer.tools.context import get_code_length
from codebase_analyzer.tools.summary import SummaryBot


def ast_type(node: ast.AST) -> str:
    """For getting the type of the ast node."""
    return node.__class__.__name__


class CodeInfoLevel(int, Enum):
    MODULE = 0
    DIRECT_CHILD = 1
    CLASS_METHOD = 2


class CodeInfo(BaseModel):
    name: str
    code: str
    length_in_token: int
    level: CodeInfoLevel
    summary: str = None
    embedding: list[float] = None


class CodeNode(BaseModel):
    # Function, class and file entrypoint are isolated nodes.
    # Isolated nodes can have children and won't be merged.
    isolated: bool
    ast: list[ast.AST]
    children: list[CodeNode] = Field(default_factory=list)
    info: CodeInfo = None
    Config = AllowArbitraryTypeConfig  # For allowing AST type for pydantic.

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other


class CodeExtractor(ast.NodeVisitor):
    def __init__(self, block_size: int = 1000, skip_token_num: int = 50) -> None:
        self.code_tree: CodeNode = None
        self.block_size: int = block_size  # in tokens
        # class method shorter than this won't be splitted.
        self.skip_token_num: int = skip_token_num

    def generic_visit(self, node: ast.AST) -> None:
        """Catches the type of node that is not handled."""
        if ast_type(node) == "Module":
            self.code_tree = CodeNode(isolated=True, ast=[node])
            super().generic_visit(node)
        else:
            self.add_with_trying_merge(node)
            logger.info(f"Other node type: {type(node)}")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.parse_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.parse_function(node)

    def visit_If(self, node: ast.If) -> None:
        """Handle the entry point of a module when being executed."""
        if self.is_file_entrypoint(node):
            # HACK: Add name to the node to simplify logic in code_info_from_ast.
            node.name = "module_entrypoint"
            self.code_tree.children.append(CodeNode(isolated=True, ast=[node]))
        else:
            self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        code_node = CodeNode(isolated=True, ast=[node])
        self.code_tree.children.append(code_node)
        if get_code_length(ast.unparse(node)) > self.block_size:
            self.split_class_methods(code_node)

    def add_with_trying_merge(
        self, node: ast.AST, parent: CodeNode | None = None
    ) -> None:
        """This method allows merging non-isolated node on the fly while traversing the AST."""
        if parent is None:
            parent = self.code_tree

        children = self.code_tree.children
        if (
            children
            and not children[-1].isolated
            and len(children) < self.block_size
        ):
            children[-1].ast.append(node)
        else:
            children.append(CodeNode(isolated=False, ast=[node]))

    def parse_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.code_tree.children.append(CodeNode(isolated=True, ast=[node]))
        code_length = get_code_length(ast.unparse(node))
        if code_length > self.block_size:
            # TODO: Split the function into smaller functions.
            logger.warning(
                f"Function {node.name} is too long after splitting. "
                f"({code_length} > {self.block_size}) line threshold."
            )

    def is_file_entrypoint(self, node: ast.If) -> bool:
        """Check if the if statement is the entry point of a module."""
        if isinstance(node.test, ast.Compare):
            left = node.test.left
            right = node.test.comparators[0]
            if (
                isinstance(left, ast.Name)
                and left.id == "__name__"
                and isinstance(right, ast.Constant)
                and right.value == "__main__"
            ):
                return True
        return False

    def split_class_methods(self, parent_node: CodeNode) -> None:
        class_node = parent_node.ast[0]
        for node in class_node.body:
            # TODO: Handle assignment and other types of statements.
            if (
                isinstance(node, ast.FunctionDef)
                or isinstance(node, ast.AsyncFunctionDef)
                or isinstance(node, ast.ClassDef)
            ):
                if get_code_length(ast.unparse(node)) <= self.skip_token_num:
                    continue
                method_name = f"{class_node.name}.{node.name}"
                parent_node.children.append(CodeNode(isolated=True, ast=[node]))
                comment = f"Function body is omitted here but accessable in block `{method_name}`."
                node.body = [ast.Expr(value=ast.Str(s=comment)), ast.Pass()]

        class_code = ast.unparse(class_node)
        if len(class_code) > self.block_size:
            logger.warning(
                f"Class {class_node.name} is still too long after splitting."
                f"({len(class_code)} > {self.block_size}) line threshold."
            )

    @classmethod
    def generate_code_tree(cls, code: str, **kwargs) -> pd.DataFrame:
        # TODO: Rethink if I can reuse the extractor for multiple files.
        tree = ast.parse(code)
        extractor = cls(**kwargs)
        extractor.visit(tree)
        return extractor.code_tree


def add_block(
    name: str,
    code: str,
    type: str,
    parent: CodeInfo = None,
) -> None:
    parent.children.append(
        CodeInfo(
            name=name,
            code=code,
            type=type,
            level=parent.level + 1,
            length_in_token=get_code_length(code=code) if code else 0,
        )
    )


def code_info_from_ast(node: CodeNode, level: int, index: int) -> None:
    """Generates code info from the AST. Summary and embedding are not populated."""

    if not node.children:
        if node.isolated:
            ast_node = node.ast[0]
            code = ast.unparse(ast_node)
            name = ast_node.name
        else:
            code = "\n".join(ast.unparse(n) for n in node.ast)
            name = f"code_block_of_level_{level}_index_{index}"
    else:
        assert len(node.ast) == 1
        assert node.isolated is True
        ast_node = node.ast[0]
        if level != CodeInfoLevel.MODULE:
            name = ast_node.name
            code = ast.unparse(ast_node)
        else:
            name = "module_structure_overview"
            code = "\n\n".join(n.info.name for n in node.children)

    node.info = CodeInfo(
        name=name,
        code=code,
        length_in_token=get_code_length(code),
        level=level,
    )


def generate_code_info(node: CodeNode, level: int = 0, index: int = 0) -> CodeInfo:
    """Recursively generate code info from code tree. A node's info can be
    generated only after all its children's info are generated."""
    for i, child in enumerate(node.children):
        generate_code_info(child, level=level + 1, index=i)
    code_info_from_ast(node, level=level, index=index)


import asyncio
from collections import defaultdict


async def populate_embedding(node: CodeNode, embeddings: OpenAIEmbeddings) -> None:
    node.info.embedding = await embeddings.aembed_query(node.info.code)


async def populate_summary(node: CodeNode, summary_bot: SummaryBot) -> None:
    node.info.summary = await summary_bot.asummarize_code(node.info.code)


async def populate_summary_and_embedding(root: CodeNode):
    todo_children = defaultdict(int)
    child_to_parent = {}
    summary_bot = SummaryBot()
    embeddings = OpenAIEmbeddings(openai_api_key=get_api_key())

    def count_children(node):
        todo_children[node] += len(node.children)
        for child in node.children:
            # todo_children[node] += 1
            child_to_parent[child] = node
            count_children(child)

    count_children(root)

    queue = asyncio.Queue()
    for node, count in todo_children.items():
        if count == 0:
            await queue.put(node)

    while not queue.empty():
        tasks = []
        while not queue.empty():
            node = await queue.get()
            tasks.extend(
                [
                    populate_embedding(node, embeddings),
                    populate_summary(node, summary_bot),
                ]
            )
            parent = child_to_parent.get(node)
            todo_children[node] -= 1  # Mark as done.
            if parent is not None:
                todo_children[parent] -= 1
        await asyncio.gather(*tasks)

        for node, count in todo_children.items():
            if count == 0:
                await queue.put(node)


# TODO: Move to test file.
code = """
from __future__ import annotations

GREETING = "Hi"

def foo():
    print(GREETING)

TEST = "test"

class Foo:
    a = 1
    b = 2

    def __init__(self):
        foo()

    def bar(self):
        print("bar")
        print("bar")
        print("bar")

if __name__=="__main__":
    Foo()
"""

t = CodeExtractor.generate_code_tree(code=code, block_size=30, skip_token_num=10)
generate_code_info(t)
asyncio.run(populate_summary_and_embedding(t))
print(t.info.summary)
