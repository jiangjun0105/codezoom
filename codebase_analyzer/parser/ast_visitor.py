from __future__ import annotations

import ast

import pandas as pd
from loguru import logger

from codebase_analyzer.parser.base import CodeNode
from codebase_analyzer.tools.context import get_code_length


def ast_type(node: ast.AST) -> str:
    """For getting the type of the ast node."""
    return node.__class__.__name__


class CodeExtractor(ast.NodeVisitor):
    """For extracting tree of code info from AST.
    TODO: Currently cannot preserve hash comments. Check tools like astor or libcst"""

    def __init__(self, block_size: int = 1000, skip_token_num: int = 50) -> None:
        self.code_tree: CodeNode = None
        self.block_size: int = block_size  # in tokens
        # class method shorter than this won't be splitted.
        self.skip_token_num: int = skip_token_num

    def generic_visit(self, node: ast.AST) -> None:
        """Catches the type of node that is not handled."""
        if ast_type(node) == "Module":  # root node
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
            self.split_class(code_node)

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

    def split_class(self, parent_node: CodeNode) -> None:
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
                parent_node.children.append(CodeNode(isolated=True, ast=[node]))
        return

    @classmethod
    def generate_code_tree(cls, code: str, **kwargs) -> pd.DataFrame:
        # TODO: Rethink if I can reuse the extractor for multiple files.
        tree = ast.parse(code)
        extractor = cls(**kwargs)
        extractor.visit(tree)
        return extractor.code_tree
