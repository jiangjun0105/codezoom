from __future__ import annotations

import ast
from enum import Enum

import pandas as pd
from loguru import logger
from pydantic import BaseModel

from codebase_analyzer.tools.context import CodeLengthUnit, get_code_length
from codebase_analyzer.tools.embedding import get_embedding
from codebase_analyzer.tools.summary import SummaryBot


class CodeBlockLevel(int, Enum):
    FILE = 0
    DIRECT_CHILD = 1
    CLASS_METHOD = 2


class CodeBlock(BaseModel):
    name: str
    code: str
    length_in_token: int  # Unit is token by default.
    level: CodeBlockLevel = CodeBlockLevel.DIRECT_CHILD
    summary: str = None
    embedding: list[float] = None


class CodeExtractor(ast.NodeVisitor):
    def __init__(self, block_lines: int = 50) -> None:
        self.code_blocks: list[
            CodeBlock
        ] = []  # Function, class and file entry point.
        self.imports: list[str] = []
        self.others: list[str] = []  # Global variables, assignments, etc.
        self.block_lines: int = block_lines  # Max lines of code in a block.
        self.converted: bool = False
        self.summary_bot: SummaryBot = SummaryBot()

    def generic_visit(self, node: ast.AST) -> None:
        """Catches the type of node that is not handled."""
        if node.__class__.__name__ == "Module":
            super().generic_visit(node)
        else:
            self.others.append(ast.unparse(node))
            logger.info(f"Other node type: {type(node)}")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.parse_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.parse_function(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.imports.append(ast.unparse(node))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.imports.append(ast.unparse(node))

    def visit_If(self, node: ast.If) -> None:
        """Handle the entry point of a module when being executed."""
        if self.is_file_entrypoint(node):
            code = ast.unparse(node)
            self.add_block(name="File entry point", code=code)
        else:
            self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        code = ast.unparse(node)
        self.add_block(name=node.name, code=code)
        if len(code) > self.block_lines:
            self.split_class_methods(node)

    def parse_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        code = ast.unparse(node)
        self.add_block(name=node.name, code=code)
        if len(code) > self.block_lines:
            # TODO: Split the function into smaller functions.
            logger.warning(
                f"Function {node.name} is too long after splitting. "
                f"({len(code)} > {self.block_lines}) line threshold."
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

    def split_class_methods(self, class_node: ast.ClassDef) -> None:
        for node in class_node.body:
            # TODO: Handle nested classes?
            if isinstance(node, ast.FunctionDef) or isinstance(
                node, ast.AsyncFunctionDef
            ):
                method_name = f"{class_node.name}.{node.name}"
                method_code = ast.unparse(node)
                self.add_block(
                    name=node.name,
                    code=method_code,
                    level=CodeBlockLevel.CLASS_METHOD,
                )
                comment = f"# Function body is omitted here but accessable in block `{method_name}`."
                node.body = [ast.Expr(value=ast.Str(s=comment)), ast.Pass()]

        class_code = ast.unparse(class_node)
        if len(class_code) > self.block_lines:
            logger.warning(
                f"Class {class_node.name} is still too long after splitting."
                f"({len(class_code)} > {self.block_lines}) line threshold."
            )
        self.code_blocks[class_node.name] = class_code

    def convert_lines_to_blocks(self) -> list[CodeBlock]:
        """Converts imports and others to code blocks."""
        if self.converted:
            logger.warning(
                "Code blocks have already been converted, won't convert again."
            )
            return

        for name, blocks in zip(
            ["module-level imports", "module-level executable statements"],
            [self.imports, self.others],
        ):
            for i, code in enumerate(self._split_list(blocks)):
                self.add_block(name=f"{name} (segment {i})", code=code)
        self.converted = True

    def _split_list(self, lines: list[str]) -> list[str]:
        """Split the lines into smaller chunks and join."""
        return [
            "\n".join(lines[i : i + self.block_lines])
            for i in range(0, len(lines), self.block_lines)
        ]

    def add_block(
        self,
        name: str,
        code: str,
        level: CodeBlockLevel = CodeBlockLevel.DIRECT_CHILD,
    ) -> None:
        self.code_blocks.append(
            CodeBlock(
                name=name,
                code=code,
                level=level,
                length_in_token=get_code_length(
                    code=code,
                    unit=CodeLengthUnit.TOKEN,
                ),
                # TODO: Rethink of the summary generation, maybe it should
                # be done centralized to run asyncly.
                summary=self.summary_bot.summarize_code(code=code),
                embedding=get_embedding(text=code),
            )
        )

    @classmethod
    def blocks_from_code(cls, code: str, block_lines: int = 50) -> pd.DataFrame:
        # TODO: Rethink if I can reuse the extractor for multiple files.
        tree = ast.parse(code)
        extractor = cls(block_lines=block_lines)
        extractor.visit(tree)
        extractor.convert_lines_to_blocks()
        return pd.DataFrame([b.dict() for b in extractor.code_blocks])


# TODO: Move to test file.
code = """
from __future__ import annotations

GREETING = "Hi"

def foo():
    print(GREETING)

class Foo:
    def __init__(self):
        foo()

if __name__=="__main__":
    Foo()
"""

# CodeExtractor.blocks_from_code(code=code)
