"""Main classes for the module bot."""

from __future__ import annotations

from pathlib import Path

from langchain.tools import StructuredTool
from loguru import logger
from pydantic import BaseModel, root_validator, validator

from codebase_analyzer.bots.executor import AgentExecutorBot
from codebase_analyzer.bots.module.prompts import SYSTEM_MESSAGE
from codebase_analyzer.parser.deftree import CodeNode
from codebase_analyzer.parser.uri import uri_to_path
from codebase_analyzer.tools.base import (
    ask_bot,
    get_code,
    get_summaries,
    semantic_search,
)
from codebase_analyzer.tools.patch import patch_tool


def read_file(path):
    file_path = Path(path)

    # TODO: rethink if we should return None or raise an error
    if not file_path.exists():
        logger.error(f"The file {path} does not exist.")
        return None

    if not file_path.is_file():
        logger.error(f"{path} is not a file.")
        return None

    try:
        data = file_path.read_text()
        return data
    except Exception as e:
        logger.error(f"An error occurred while reading the file: {e}")
        return None


def get_cache_path(cache_root: Path, relative_path: Path) -> Path:
    """Gets the cache path for the given repo and file paths."""
    if relative_path.is_absolute():
        raise ValueError(
            f"relative_path must be relative to repo_root, but got {relative_path}"
        )

    # Cache uses the same folder structure as the repo but create a new folder
    # for each file, e.g. src/main.py -> src/main_py/
    return cache_root / relative_path.parent / relative_path.name.replace(".", "_")


class ModuleBot(AgentExecutorBot):
    """A bot managing a module (module)."""

    @staticmethod
    def get_system_message(code_node: CodeNode) -> str:
        return SYSTEM_MESSAGE.format(
            module_path=uri_to_path(code_node.uri),
            module_summary=code_node.summary,
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
            StructuredTool.from_function(
                func=patch_tool(
                    get_code, ask_manager=ask_manager, ask_by=code_node.uri
                )
            ),
            StructuredTool.from_function(
                func=patch_tool(get_summaries, summaries=summary_sheet)
            ),
        ]
        return values
