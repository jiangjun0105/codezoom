from __future__ import annotations

import ast
from enum import Enum
from pathlib import Path

import pandas as pd
from loguru import logger
from pydantic import BaseModel, Field

from codebase_analyzer.common.pydantic import AllowArbitraryTypeConfig
from codebase_analyzer.tools.context import get_code_length


def ast_type(node: ast.AST) -> str:
    """For getting the type of the ast node."""
    return node.__class__.__name__


class DefTreeExtractor(ast.NodeVisitor):
    """For extracting the definition tree of a python module from AST.
    TODO: Currently cannot preserve hash comments. Check tools like astor or libcst"""

    def __init__(
        self,
        *,
        block_size: int = 1000,
        skip_token_num: int = 50,
    ) -> None:
        self.block_size: int = block_size  # in tokens
        # class method shorter than this won't be splitted.
        self.skip_token_num: int = skip_token_num

    def visit(
        self, *, node: ast.AST, level: int, parent: CodeNode, **kwargs
    ) -> None:
        """Visit a node."""
        method = "visit_" + node.__class__.__name__
        visitor = getattr(self, method, self.generic_visit)
        return visitor(node=node, level=level, parent=parent, **kwargs)

    def visit_module_children(
        self, *, node: ast.AST, parent: CodeNode, level: int
    ) -> None:
        """Visits all children of input node. Each child could be a node or a list of nodes.
        This is actually the generic_visit method in ast.NodeVisitor."""
        for _field, value in ast.iter_fields(node):
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        self.visit(node=item, level=level, parent=parent)
            elif isinstance(value, ast.AST):
                self.visit(node=value, level=level, parent=parent)

    def generic_visit(self, *, node: ast.AST, level: int, parent: CodeNode) -> None:
        """Catches the type of node that is not handled."""
        self.add_with_trying_merge(node=node, level=level, parent=parent)
        logger.info(f"Other node type: {type(node)}")

    def visit_Module(
        self, *, node: ast.AST, level: int, parent: CodeNode, uri: str
    ) -> None:
        """Extracts the root node of the module."""
        if ast_type(node) != "Module":
            raise ValueError(f"Node type must be Module, but got {ast_type(node)}")

        return CodeNode(
            uri=uri,
            merged=False,
            ast=[node],
            level=level,
            type=NodeType.MODULE,
            parent=parent,
        )

    def visit_FunctionDef(
        self, *, node: ast.FunctionDef, level: int, parent: CodeNode
    ) -> None:
        self.parse_function(
            node=node,
            level=level,
            parent=parent,
        )

    def visit_AsyncFunctionDef(
        self, *, node: ast.AsyncFunctionDef, level: int, parent: CodeNode
    ) -> None:
        self.parse_function(
            node=node,
            level=level,
            parent=parent,
        )

    def visit_If(self, *, node: ast.If, level: int, parent: CodeNode) -> None:
        """Handle the entry point of a module when being executed."""
        if self.is_file_entrypoint(node=node):
            # HACK: Add name to the node to simplify logic in code_info_from_ast.
            node.name = "script execution block"
            parent.children.append(
                CodeNode(
                    uri=self._uri(node=node, parent=parent),
                    merged=False,
                    ast=[node],
                    type=NodeType.ENTRYPOINT,
                    level=level,
                    parent=parent,
                )
            )
        else:
            self.generic_visit(node=node, level=level, parent=parent)

    def visit_ClassDef(
        self, *, node: ast.ClassDef, level: int, parent: CodeNode
    ) -> None:
        code_node = CodeNode(
            uri=self._uri(node=node, parent=parent),
            merged=False,
            ast=[node],
            type=NodeType.CLASS,
            level=level,
            parent=parent,
        )
        parent.children.append(code_node)
        if get_code_length(ast.unparse(node)) > self.block_size:
            self.split_class(parent=code_node, level=level + 1)

    def add_with_trying_merge(
        self, *, node: ast.AST, level: int, parent: CodeNode
    ) -> None:
        """This method allows merging non-isolated node on the fly while traversing the AST."""
        if parent is None:
            raise ValueError("Parent cannot be None.")

        children = parent.children
        if children and children[-1].merged and len(children) < self.block_size:
            children[-1].ast.append(node)
        else:
            children.append(
                CodeNode(
                    merged=True,
                    uri=self._uri(node=node, parent=parent),
                    level=level,
                    ast=[node],
                    parent=parent,
                    type=NodeType.STATEMENT,
                )
            )

    def _uri(self, *, node: ast.AST, parent: CodeNode) -> str:
        """Generates the uri of a node."""
        if parent is None:
            raise ValueError("Parent cannot be None.")
        try:
            return parent.uri + "." + node.name
        except AttributeError:
            logger.info(f"Use 'statements' as end uri for {node=} with {parent=}.")
            return parent.uri + "." + "statements"

    def parse_function(
        self,
        *,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        level: int,
        parent: CodeNode,
    ) -> None:
        parent.children.append(
            CodeNode(
                merged=False,
                uri=self._uri(node=node, parent=parent),
                ast=[node],
                level=level,
                parent=parent,
                type=NodeType.FUNCTION,
            )
        )
        code_length = get_code_length(ast.unparse(node))
        if code_length > self.block_size:
            # TODO: Split the function into smaller functions.
            logger.warning(
                f"Function {node.name} is too long after splitting. "
                f"({code_length} > {self.block_size}) line threshold."
            )

    def is_file_entrypoint(self, *, node: ast.If) -> bool:
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

    def split_class(self, *, parent: CodeNode, level: int) -> None:
        class_node = parent.ast[0]
        for node in class_node.body:
            # TODO: Handle assignment and other types of statements.
            if (
                isinstance(node, ast.FunctionDef)
                or isinstance(node, ast.AsyncFunctionDef)
                or isinstance(node, ast.ClassDef)
            ):
                if get_code_length(ast.unparse(node)) <= self.skip_token_num:
                    continue
                parent.children.append(
                    CodeNode(
                        uri=self._uri(node, parent),
                        merged=False,
                        ast=[node],
                        level=level,
                        parent=parent,
                        type=NodeType.CLASS_METHOD,
                    )
                )
        return

    def generate_def_tree(
        self, *, code: str, uri: str, level: int, parent: CodeNode | None
    ) -> CodeNode:
        ast_root = ast.parse(code)
        root = self.visit_Module(node=ast_root, uri=uri, level=level, parent=parent)
        self.visit_module_children(node=ast_root, parent=root, level=level + 1)
        return root


class NodeType(str, Enum):
    PACKAGE = "package"
    MODULE = "module"
    ENTRYPOINT = "entrypoint"
    STATEMENT = "statement"
    FUNCTION = "function"
    CLASS = "class"
    CLASS_METHOD = "class_method"


class CodeInfo(BaseModel):
    name: str
    code: str
    length_in_token: int
    level: int
    index: int
    summary: str = None
    embedding: list[float] = None


def _uri(*, path: Path, parent: CodeNode) -> str:
    uri = path.name
    if parent:
        uri = parent.uri + "." + uri
    return uri


class CodeNode(BaseModel):
    uri: str = Field(..., description="Node Uniform Resource Idendifier.")
    merged: bool = Field(
        default=False, description="If the node is merged from multiple ast nodes."
    )
    type: str = Field(...)
    level: int = Field(...)
    ast: list[ast.AST] = Field(default_factory=list)
    children: list[CodeNode] = Field(default_factory=list)
    parent: CodeNode | None = None
    info: CodeInfo | None = None
    Config = AllowArbitraryTypeConfig  # For allowing AST type for pydantic.

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other

    @classmethod
    def from_folder(
        cls,
        *,
        path: Path,
        level: int,
        parent: CodeNode,
        extractor: DefTreeExtractor,
    ) -> CodeNode:
        """Generates a CodeNode from a folder."""
        if not path.is_dir():
            raise ValueError(f"{path} is not a folder.")

        node = cls(
            uri=_uri(path=path, parent=parent),
            level=level,
            type=NodeType.PACKAGE,
            path=path,
            parent=parent,
        )

        node.children = [
            cls.from_folder(
                path=child, level=level + 1, parent=node, extractor=extractor
            )
            if child.is_dir()
            else cls.from_file(
                path=child, level=level + 1, parent=node, extractor=extractor
            )
            for child in path.iterdir()
        ]

        return node

    @classmethod
    def from_file(
        cls,
        *,
        path: Path,
        level: int,
        parent: CodeNode,
        extractor: DefTreeExtractor,
    ) -> CodeNode:
        """Generates a CodeNode from a file."""
        code = path.expanduser().read_text()
        return extractor.generate_def_tree(
            uri=_uri(path=path, parent=parent),
            code=code,
            level=level,
            parent=parent,
        )


def generate_def_tree(repo_root: Path, **kwargs) -> CodeNode:
    """Generates the definition tree of the given repository."""
    ns_to_node: dict[CodeNode, CodeNode] = dict()
    root = CodeNode.from_folder(
        path=repo_root,
        level=0,
        parent=None,
        extractor=DefTreeExtractor(**kwargs),
    )
    return root


if __name__ == "__main__":
    p = Path("~/ichigen-coder/codebase_analyzer/tests/").expanduser()

    generate_def_tree(repo_root=p)
