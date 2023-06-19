from __future__ import annotations

from functools import partial
from typing import Any, Callable

from loguru import logger

from codebase_analyzer import commands
from codebase_analyzer.chatbot import Chatbot
from codebase_analyzer.embedding import search_functions


class Tool:
    def __init__(
        self,
        command: Callable,
        instruction: str,
        name: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.name = name or command.__name__
        self._command = command
        self._instruction = instruction
        self._kwargs = kwargs

    def __call__(self, *args, **kwargs) -> Any:
        return self._command(*args, **kwargs, **self._kwargs)

    def update(self, **kwargs) -> Any:
        self._kwargs.update(kwargs)
        return self

    @property
    def command(self) -> Callable:
        return partial(self._command, **self._kwargs)

    @property
    def instruction(self) -> str:
        return self._instruction


class ToolSet(dict):
    def __init__(self, *tools) -> None:
        super().__init__({t.name: t for t in tools})

    @property
    def instructions(self) -> str:
        return "\n".join(
            [f"{name}: {tool.instruction}" for name, tool in self.items()]
        )


# NOTE: Be careful the name conflicts between the commands and the tools.
get_relevant_functions = Tool(
    command=commands.get_relevant_functions,
    instruction="""
- get_relevant_functions("<detailed_description_about_what_you_want>", "<code/summary>")
    to search for the function most relevant to your description and return its code or summary.
    E.g. get_relevant_functions("Completions API test", "code")  # returns function code most relevant to "Completions API test"
    E.g. get_relevant_functions("Completions API test", "summary")  # returns function summary
""",
)

get_directory_tree = Tool(
    command=commands.get_directory_tree,
    instruction="""
- get_directory_tree(path="<path_to_directory>", level=<int>)
    to get the directory tree of the given codebase. "./" is the root directory.
    Recommend to set level to 1 or 2 to prevent the output exceed your context window.
    E.g. directory_tree(path="./", level=2)
""",
)


get_file_content = Tool(
    command=commands.get_file_content,
    instruction="""
- get_file_content(path="<path_to_file>")
    to get the content of the given file. "./" is the root directory.
    E.g. get_file_content(path="./codebase_analyzer/bots.py")
""",
)
