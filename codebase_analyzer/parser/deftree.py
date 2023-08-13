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


def _extract_code(node: ast.AST, type: NodeType) -> str:
    if type in (
        NodeType.FUNCTION,
        NodeType.CLASS_METHOD,
        NodeType.STATEMENT,  # Should be the first statement in the CodeNode
        NodeType.ENTRYPOINT,
    ):
        return ast.unparse(node)
    if type in (NodeType.CLASS, NodeType.MODULE):
        return (
            f"TODO: Code of node {type=} should be done after children are generated"
        )
    raise ValueError(f"Cannot extract code for {type=}")


def _omit_function_body(ast_node: ast.AST, code_node: CodeNode) -> None:
    """For long class or function, omit its children code for brevity."""
    assert code_node.code is not None
    comment = (
        f"NOTE: function body is ommited here. See {code_node.uri} for details."
    )
    ast_node.body = [ast.Expr(value=ast.Str(s=comment))]


class DefTreeExtractor(ast.NodeVisitor):
    """For extracting the definition tree of a python module from AST.
    TODO: Currently cannot preserve hash comments. Check tools like astor or libcst"""

    def __init__(
        self,
        *,
        block_size: int = 1000,
        skip_token_num: int = 50,
    ) -> None:
        # Function having more than this number of tokens will throw a warning.
        # Statement nodes having more than this number of tokens will stop merging new statements.
        self.block_size: int = block_size  # in tokens
        # class method shorter than this won't be splitted. Disabled for now.
        self.skip_token_num: int = skip_token_num
        # Currently only the nodes could be called are added to self.uri2node.
        self.uri2node: dict[str, CodeNode] = dict()

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
        return self._add_code_node(
            node=node, uri=uri, parent=parent, level=level, type=NodeType.MODULE
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
            node.name = "[entrypoint]"
            self._add_code_node(
                node=node, parent=parent, level=level, type=NodeType.ENTRYPOINT
            )
        else:
            self.generic_visit(node=node, level=level, parent=parent)

    def visit_ClassDef(
        self, *, node: ast.ClassDef, level: int, parent: CodeNode
    ) -> None:
        class_code_node = self._add_code_node(
            node=node, parent=parent, level=level, type=NodeType.CLASS
        )

        # Extract class methods as CodeNodes.
        for child_node in node.body:
            # TODO: Handle assignment and other types of statements.
            if (
                isinstance(child_node, ast.FunctionDef)
                or isinstance(child_node, ast.AsyncFunctionDef)
                or isinstance(child_node, ast.ClassDef)
            ):
                self._add_code_node(
                    node=child_node,
                    parent=class_code_node,
                    level=level + 1,
                    type=NodeType.CLASS_METHOD,
                )
                # _omit_function_body(ast_node=child_node, code_node=child_code_node)

        # class_code_node.code = ast.unparse(node)
        # class_code_node.code_length_tokens = get_code_length(class_code_node.code)

    def add_with_trying_merge(
        self, *, node: ast.AST, level: int, parent: CodeNode
    ) -> None:
        """This method allows merging non-isolated node on the fly while traversing the AST."""
        if parent is None:
            raise ValueError("Parent cannot be None.")

        last = parent.children[-1] if parent.children else None

        if last and last.merged and last.code_length_tokens < self.block_size:
            last.code += f"\n{ast.unparse(node)}"
            last.code_length_tokens = get_code_length(last.code)
        else:
            self._add_code_node(
                node=node,
                parent=parent,
                level=level,
                type=NodeType.STATEMENT,
                merged=True,
            )

    def _uri(self, *, node: ast.AST, parent: CodeNode) -> str:
        """Generates the uri of a node. See more in _uri function."""
        if parent is None:
            raise ValueError("Parent cannot be None.")

        # Module node.uri is suffixed with a slash so no need to add seg here.
        seg = "" if parent.type == NodeType.MODULE else "."
        try:
            return parent.uri + seg + node.name
        except AttributeError:
            logger.info(f"Use 'statements' as end uri for {node=} with {parent=}.")
            # Has to be something impossible to be a function/class name.
            # FIXME: There could be two statements with the same name.
            _STATEMENTS_URI = "[statements]"
            return parent.uri + seg + _STATEMENTS_URI

    def parse_function(
        self,
        *,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        level: int,
        parent: CodeNode,
    ) -> None:
        self._add_code_node(
            node=node, parent=parent, level=level, type=NodeType.FUNCTION
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

    def _add_code_node(
        self,
        *,
        node: ast.AST,
        level: int,
        parent: CodeNode,
        type: NodeType,
        uri: str | None = None,
        merged: bool = False,
    ) -> None:
        """Adds a code node to the tree."""
        assert uri is None or type == NodeType.MODULE

        # The whole code is extracted here but will be processed again when
        # generating summaries.
        code = ast.unparse(node)
        code_node = CodeNode(
            uri=uri or self._uri(node=node, parent=parent),
            merged=merged,
            code=code,
            code_length_tokens=get_code_length(code),
            level=level,
            parent=parent,
            type=type,
        )
        parent.children.append(code_node)
        self.uri2node[code_node.uri] = code_node
        return code_node

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


def _uri(*, path: Path, parent: CodeNode, root_prefix: str = "") -> str:
    """Generates the Universal Resource Identifier (URI) of a node based on its path
    and parent node. E.g. of uri: /path.subpath.filename/Class.method(). The uri
    after filename is handled by DefTreeExtractor._uri function."""
    if parent:
        seg = "" if parent.uri == "/" else "."
        end = "/" if path.is_file() else ""
        return parent.uri + seg + path.stem + end
    else:
        return root_prefix or "/"


class CodeNode(BaseModel):
    uri: str = Field(..., description="Node Uniform Resource Idendifier.")
    merged: bool = Field(
        default=False, description="If the node is merged from multiple ast nodes."
    )
    type: str = Field(..., description="See NodeType class.")
    level: int = Field(..., description="The level of the node in the whole tree.")
    # ast: list[ast.AST] = Field(default_factory=list)
    code: str | None = Field(None, description="Code for non-package nodes.")
    code_length_tokens: int | None = Field(
        None, description="Code length in tokens."
    )
    index: int = None
    summary: str = None
    embedding: list[float] = None
    children: list[CodeNode] = Field(default_factory=list)
    parent: CodeNode | None = None
    calls: list[CodeNode] = Field(
        default_factory=list, description="Nodes called by this node."
    )
    called_by: list[CodeNode] = Field(
        default_factory=list, description="Nodes calling this node."
    )
    superclasses: list[CodeNode] = Field(default_factory=list)
    subclasses: list[CodeNode] = Field(default_factory=list)

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
        parent: CodeNode | None,
        uri_prefix: str = "",
        extractor: DefTreeExtractor,
    ) -> CodeNode:
        """Generates a CodeNode from a folder."""
        if not path.is_dir():
            raise ValueError(f"{path} is not a folder.")

        node = cls(
            uri=_uri(path=path, parent=parent, root_prefix=uri_prefix),
            level=level,
            type=NodeType.PACKAGE,
            path=path,
            parent=parent,
        )

        for child in path.iterdir():
            if child.is_dir():
                node.children.append(
                    cls.from_folder(
                        path=child, level=level + 1, parent=node, extractor=extractor
                    )
                )
            elif child.suffix == ".py":
                # Adding to parent.children is handled inside extractor
                cls.from_file(
                    path=child, level=level + 1, parent=node, extractor=extractor
                )
            else:
                continue

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


def generate_def_tree(
    repo_root: Path, uri_prefix: str = "", **kwargs
) -> tuple[CodeNode, dict[str, CodeNode]]:
    """Generates the definition tree of the given repository."""
    if not repo_root.exists():
        raise ValueError(f"{repo_root=} doesn't exist.")

    extractor = DefTreeExtractor(**kwargs)
    root = CodeNode.from_folder(
        path=repo_root,
        level=0,
        parent=None,
        uri_prefix=uri_prefix,
        extractor=extractor,
    )
    return root, extractor.uri2node


if __name__ == "__main__":
    p = Path(
        "/Users/jun/Projects/ichigen-coder/codebase_analyzer/tests/"
    ).expanduser()

    node = generate_def_tree(repo_root=p)
    pass
