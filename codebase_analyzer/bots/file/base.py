"""Main classes for the file bot."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, ClassVar

import pandas as pd
from langchain.agents import AgentExecutor
from langchain.agents.openai_functions_agent.base import OpenAIFunctionsAgent
from langchain.chat_models import ChatOpenAI
from langchain.memory import ConversationBufferMemory
from langchain.prompts.chat import MessagesPlaceholder
from langchain.schema import SystemMessage
from langchain.tools import StructuredTool
from loguru import logger
from pydantic import BaseModel, root_validator, validator

from codebase_analyzer.bots.base import Bot
from codebase_analyzer.bots.callbacks import BotStreamingStdOutCallbackHandler
from codebase_analyzer.bots.file import config
from codebase_analyzer.bots.file.prompts import SYSTEM_MESSAGE
from codebase_analyzer.parser.parser import (
    extract_code_info,
    load_cached_codebase_info,
)
from codebase_analyzer.tools import (
    ask_function_bot,
    get_file_summary,
    get_function_code,
    get_function_summaries,
    get_related_functions,
    patch_tool,
)


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


class Cache(BaseModel):
    pass


def get_cache_path(cache_root: Path, file_path: Path) -> Path:
    """Gets the cache path for the given repo and file paths."""
    if file_path.is_absolute():
        raise ValueError(
            f"file_path must be relative to repo_root, but got {file_path}"
        )

    # Cache uses the same folder structure as the repo but create a new folder
    # for each file, e.g. main.py -> main_py
    return cache_root / file_path.parent / file_path.name.replace(".", "_")


class AllowArbitraryTypeConfig(BaseModel.Config):
    # Used by pydantic to allow arbitrary type e.g. pd.DataFrame
    arbitrary_types_allowed = True


class FileCache(BaseModel):
    """Cache for a single file."""

    FILE_SUMMARY: ClassVar[str] = "file.md"
    FUNCTIONS_SUMMARY: ClassVar[str] = "functions.md"
    CODE_INFO: ClassVar[str] = "code_info.csv"

    Config = AllowArbitraryTypeConfig
    cache_path: Path
    file_summary: str
    function_summary: str
    code_info: pd.DataFrame

    @classmethod
    def load_from_disk(cls, cache_root: Path, file_path: Path) -> FileCache:
        cache_path = get_cache_path(cache_root=cache_root, file_path=file_path)
        return cls(
            cache_path=cache_path,
            file_summary=read_file(path=cache_path / cls.FILE_SUMMARY),
            function_summary=read_file(path=cache_path / cls.FUNCTIONS_SUMMARY),
            code_info=load_cached_codebase_info(path=cache_path / cls.CODE_INFO),
        )

    @validator("code_info")
    def validate_code_info(cls, code_info: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(code_info, pd.DataFrame):
            raise ValueError(
                f"code_info must be pd.DataFrame, cannot be {type(code_info)}"
            )
        if code_info.empty:
            raise ValueError("code_info cannot be empty")
        for column in ["name", "code"]:
            if column not in code_info.columns:
                raise ValueError(f"code_info must have '{column}' column")
        return code_info

    def save_to_disk(self, path: Path | None = None) -> None:
        if path is None:
            path = self.cache_path
        path.mkdir(parents=True, exist_ok=True)
        self.code_info.to_csv(path / self.CODE_INFO, index=False)
        (path / self.FILE_SUMMARY).write_text(self.file_summary)
        (path / self.FUNCTIONS_SUMMARY).write_text(self.function_summary)


class FileBot(Bot):
    llm = ChatOpenAI
    repo_root: Path
    file_path: Path  # Relative path to repo root
    cache: FileCache
    tools: list[StructuredTool]
    executor: AgentExecutor
    get_bot_func: Callable

    @classmethod
    def from_cache(
        cls, repo_root: Path, cache_root: Path, file_path: Path, **kwargs: Any
    ) -> FileBot:
        return cls(
            repo_root=repo_root,
            file_path=file_path,
            cache=FileCache.load_from_disk(
                cache_root=cache_root, file_path=file_path
            ),
            **kwargs,
        )

    # TODO: Add method without loading cache

    @root_validator(pre=True)
    def init_tools(cls, values: dict) -> dict:
        repo_root = values.get("repo_root")
        file_path = values.get("file_path")
        cache = values.get("cache")
        get_bot_func = values.get("get_bot_func")

        values["tools"] = [
            StructuredTool.from_function(
                func=patch_tool(
                    get_related_functions,
                    code_info=cache.code_info,
                    want="name",
                    n=5,
                )
            ),
            StructuredTool.from_function(
                func=patch_tool(get_function_code, code_info=cache.code_info)
            ),
            StructuredTool.from_function(
                func=patch_tool(get_function_summaries, code_info=cache.code_info)
            ),
            StructuredTool.from_function(
                func=patch_tool(
                    ask_function_bot,
                    file_abs_path=repo_root / file_path,
                    code_info=cache.code_info,
                    get_bot_func=get_bot_func,
                )
            ),
        ]
        return values

    @root_validator(pre=True)
    def init_agent_executor(cls, values: dict) -> dict:
        tools = values.get("tools")
        file_path = values.get("file_path")
        agent = OpenAIFunctionsAgent.from_llm_and_tools(
            llm=config.LLM,
            tools=tools,
            system_message=SystemMessage(
                # TODO: Should I use langchain.prompt?
                content=SYSTEM_MESSAGE.format(
                    file_summary=get_file_summary(file_path)
                )
            ),
            extra_prompt_messages=[MessagesPlaceholder(variable_name="history")],
        )

        values["executor"] = AgentExecutor.from_agent_and_tools(
            agent=agent,
            tools=tools,
            verbose=True,
            return_intermediate_steps=True,
            memory=ConversationBufferMemory(
                memory_key="history",
                return_messages=True,
                output_key="output",
            ),
        )
        return values

    def ask(self, inputs: str):
        # REMINDER: This function outputs final response and intermediate steps,
        # maybe I can make use of it.
        self.executor(
            inputs=inputs,
            callbacks=[BotStreamingStdOutCallbackHandler()],
        )

    def save_cache(self) -> None:
        self.cache.save_to_disk()
