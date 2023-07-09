"""Methods or data structures that are shared by multiple parsers."""
from __future__ import annotations

import ast
from enum import Enum
from pathlib import Path

# from codebase_analyzer.parser.codeinfo import CodeExtractor


class CodeInfoLevel(int, Enum):
    MODULE = 0
    DIRECT_CHILD = 1
    NESTED_CHILD = 2
