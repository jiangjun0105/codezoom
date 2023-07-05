import asyncio

from codebase_analyzer.parser.ast_visitor import CodeExtractor
from codebase_analyzer.parser.codeinfo import (
    check_code_info,
    populate_summary_and_embedding,
)

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


def test_code_info_from_ast():
    block_size = 30
    skip_token_num = 10
    code_tree = CodeExtractor.generate_code_tree(
        code=code,
        block_size=block_size,
        skip_token_num=skip_token_num,
    )
    code_info = asyncio.run(populate_summary_and_embedding(code_tree))
    check_code_info(code_info, block_size=block_size)
    # TODO: more check on code_info
    assert len(code_info) == 7
