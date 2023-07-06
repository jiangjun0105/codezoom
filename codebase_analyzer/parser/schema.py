"""Methods or data structures that are shared by multiple parsers."""
from __future__ import annotations

import ast
from enum import Enum

from pydantic import BaseModel, Field

from codebase_analyzer.common.pydantic import AllowArbitraryTypeConfig


class CodeInfoLevel(int, Enum):
    MODULE = 0
    DIRECT_CHILD = 1
    NESTED_CHILD = 2


class CodeInfo(BaseModel):
    name: str
    code: str
    length_in_token: int
    level: CodeInfoLevel
    index: int
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
