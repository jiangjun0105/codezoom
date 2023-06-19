from __future__ import annotations

from codebase_analyzer import tools


def test_tool() -> None:
    # Given
    def test_func(a: int, b: int, c: int = 0) -> int:
        return a + b + c

    # When
    tool = tools.Tool(command=test_func, prompt="test prompt")
    res = tool(1, 2)

    # Then
    assert res == 3
    assert tool.prompt == "test prompt"
    assert tool.name == "test_func"
    assert tool.command(1, 2) == 3
    assert tool.command(1, 2, c=3) == 6
    tool.update(c=3)
    assert tool.command(1, 2) == 6
    assert tool.command(1, 2, c=4) == 7
    tool.name = "test_tool"
    assert tool.name == "test_tool"


def test_tool_set() -> None:

    t1 = tools.Tool(command=lambda x: x, prompt="test prompt1", name="test_tool1")
    t2 = tools.Tool(command=lambda x: x, prompt="test prompt2", name="test_tool2")
    tool_set = tools.ToolSet(t1, t2)

    assert tool_set.get("test_tool1").prompt == "test prompt1"
    assert tool_set == {"test_tool1": t1, "test_tool2": t2}
    assert tool_set.prompts == "test_tool1: test prompt1\ntest_tool2: test prompt2"
