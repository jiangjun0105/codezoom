"""Main classes for the package bot."""

from __future__ import annotations

from pathlib import Path

from langchain.tools import StructuredTool
from pydantic import BaseModel, root_validator, validator

from codebase_analyzer.bots.executor import AgentExecutorBot
from codebase_analyzer.bots.package.prompts import SYSTEM_MESSAGE
from codebase_analyzer.parser.deftree import CodeNode
from codebase_analyzer.parser.uri import uri_to_path
from codebase_analyzer.tools.base import (
    ask_bot,
    get_code,
    get_summaries,
    semantic_search,
)
from codebase_analyzer.tools.patch import patch_tool


class PackageBot(AgentExecutorBot):
    """A bot managing a package (file)."""

    @staticmethod
    def get_system_message(code_node: CodeNode) -> str:
        return SYSTEM_MESSAGE.format(
            path=uri_to_path(code_node.uri),
            summary=code_node.summary,
        )

    @root_validator(pre=True)
    def init_tools(cls, values: dict) -> dict:
        code_node = values.get("code_node")
        ask_manager = values.get("ask_manager")
        summary_sheet = values.get("summary_sheet")

        values["tools"] = [
            StructuredTool.from_function(
                # TODO: not hardcode n but based on similarity
                func=patch_tool(
                    semantic_search,
                    ask_manager=ask_manager,
                    ask_by=code_node.uri,
                    n=5,
                )
            ),
            StructuredTool.from_function(
                func=patch_tool(
                    ask_bot, ask_manager=ask_manager, ask_by=code_node.uri
                )
            ),
            # TODO: Safeguard for get_code in case getting all code from a module
            StructuredTool.from_function(
                func=patch_tool(
                    get_code, ask_manager=ask_manager, ask_by=code_node.uri
                )
            ),
            StructuredTool.from_function(
                func=patch_tool(get_summaries, summaries=summary_sheet)
            ),
            # TODO: Add tools to get folder tree.
        ]
        return values
