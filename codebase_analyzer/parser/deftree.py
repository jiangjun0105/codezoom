from __future__ import annotations

import ast
import json
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger
from pydantic import BaseModel, Field

from codebase_analyzer.parser.callgraph import URI
from codebase_analyzer.tools.context import get_code_length


def ast_type(node: ast.AST) -> str:
    """For getting the type of the ast node."""
    return node.__class__.__name__


def should_split_class_child(node: ast.AST) -> bool:
    """Check if a certain type of ast node of a class should be splitted."""
    return (
        isinstance(node, ast.FunctionDef)
        or isinstance(node, ast.AsyncFunctionDef)
        or isinstance(node, ast.ClassDef)
    )


def uri_from_ast(*, node: ast.AST, parent: CodeNode, type: NodeType) -> str:
    """Generates the uri of a node. See more in _uri function."""
    if parent is None:
        raise ValueError("Parent cannot be None.")

    # Module node.uri is suffixed with a slash so no need to add seg here.
    seg = "" if parent.type == NodeType.MODULE else "."
    if type == NodeType.STATEMENT:
        name = f"[{type}_lineno_{node.lineno}]"
    else:
        name = node.name
    return parent.uri + seg + name


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
                raise ValueError("This should not happen.")
                self.visit(node=value, level=level, parent=parent)

    def generic_visit(self, *, node: ast.AST, level: int, parent: CodeNode) -> None:
        """Catches the type of node that is not handled. Usually statements."""
        self.add_with_trying_merge(node=node, level=level, parent=parent)
        # logger.info(f"Other node type: {type(node)}")

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
        self.parse_function(node=node, level=level, parent=parent)

    def visit_AsyncFunctionDef(
        self, *, node: ast.AsyncFunctionDef, level: int, parent: CodeNode
    ) -> None:
        self.parse_function(node=node, level=level, parent=parent)

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
            if should_split_class_child(child_node):
                self._add_code_node(
                    node=child_node,
                    parent=class_code_node,
                    level=level + 1,
                    type=NodeType.CLASS_METHOD,
                )

    def add_with_trying_merge(
        self, *, node: ast.AST, level: int, parent: CodeNode
    ) -> None:
        """This method allows merging non-isolated node on the fly while traversing the AST."""
        if parent is None:
            raise ValueError("Parent cannot be None.")

        last = self.uri2node[parent.children[-1]] if parent.children else None

        if last and last.merged and last.code_length < self.block_size:
            last.code += f"\n{ast.unparse(node)}"
            last.code_length = get_code_length(last.code)
        else:
            self._add_code_node(
                node=node,
                parent=parent,
                level=level,
                type=NodeType.STATEMENT,
                merged=True,
            )

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
        assert parent is not None

        # The whole code is extracted here but will be processed again when
        # generating summaries.
        code = ast.unparse(node)
        if code.startswith("@overload"):
            # TODO: For now we skip overloads for avoiding duplicate nodes.
            #       But we need a more reasonable way to handle overloads.
            return
        lineno = None if type == NodeType.MODULE else node.lineno
        code_node = CodeNode(
            uri=uri or uri_from_ast(node=node, parent=parent, type=type),
            merged=merged,
            code=code,
            lineno=lineno,
            code_length=get_code_length(code),
            level=level,
            parent=parent.uri,
            type=type,
        )

        parent.children.append(code_node.uri)
        if code_node.uri in self.uri2node:
            # TODO: Change to warning in production?
            print(f"{code_node.uri} already exists: {self.uri2node[code_node.uri]}.")
            # code_node.uri += f"_{code_node.lineno}"
            # raise ValueError(f"{code_node.uri} already exists.")
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
    # Common fields for all nodes
    uri: str = Field(..., description="Node Uniform Resource Idendifier.")
    type: str = Field(..., description="See NodeType class.")
    level: int = Field(..., description="The level of the node in the whole tree.")
    summary: str = None
    embedding: list[float] = None
    children: list[URI] = Field(default_factory=list)
    parent: URI | None = None

    # Only for nodes having code.
    merged: bool = Field(
        default=False, description="If the node is merged from multiple ast nodes."
    )
    code: str | None = Field(default=None, description="Code for non-package nodes.")
    code_length: int | None = Field(
        default=None,
        description="Length of code in tokens. Omited code for classes(?).",
    )
    lineno: int = Field(
        default=None, description="Number of code starting line in the file."
    )
    calls: list[URI] = Field(
        default_factory=list, description="Nodes called by this node."
    )
    called_by: list[URI] = Field(
        default_factory=list, description="Nodes calling this node."
    )
    superclasses: list[URI] = Field(default_factory=list)
    subclasses: list[URI] = Field(default_factory=list)

    # For allowing AST type for pydantic.
    # Config = AllowArbitraryTypeConfig

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
            parent=parent.uri if parent else None,
        )

        for child in path.iterdir():
            if child.is_dir():
                node.children.append(
                    cls.from_folder(
                        path=child, level=level + 1, parent=node, extractor=extractor
                    ).uri
                )
            elif child.suffix == ".py":
                # Adding to parent.children is handled inside extractor
                cls.from_file(
                    path=child, level=level + 1, parent=node, extractor=extractor
                )
            else:
                continue
        # Registration of Module and lower level nodes are handled inside extractor
        if node.uri in extractor.uri2node:
            raise ValueError(f"{node.uri} already exists.")
        extractor.uri2node[node.uri] = node
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


class CodeInfoMetadata(BaseModel):
    """Metadata for CodeInfo."""

    root: URI
    count: int


class CodeInfo(BaseModel):
    """Code information for a single file."""

    metadata: CodeInfoMetadata
    nodes: dict[URI, CodeNode]

    @property
    def root_node(self) -> CodeNode:
        return self.nodes[self.metadata.root]

    def to_disk(self, output_path: Path) -> None:
        """Saves the nodes into disk."""
        # TODO: save summaries and embeddings separately to a vector store.
        with open(output_path, "w") as f:
            json.dump(self, f, default=lambda n: n.dict())

    @classmethod
    def from_disk(cls, input_path: Path) -> CodeInfo:
        with open(input_path, "r") as f:
            cache = json.load(f)
        return cls(**cache)


def generate_def_tree(repo_root: Path, uri_prefix: str = "", **kwargs) -> CodeInfo:
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
    return CodeInfo(
        nodes=extractor.uri2node,
        metadata=dict(
            root=root.uri,
            count=len(extractor.uri2node),
        ),
    )


# TODO: Organize the following tests into a test file.
# if __name__ == "__main__":
#     p = Path(
#         "/Users/jun/Projects/ichigen-coder/codebase_analyzer/tests/"
#     ).expanduser()

#     root_node, uri2node = generate_def_tree(repo_root=p)
#     pass
