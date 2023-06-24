from pathlib import Path
from typing import Callable

import pandas as pd
from langchain.agents import AgentExecutor
from langchain.agents.openai_functions_agent.base import OpenAIFunctionsAgent
from langchain.chat_models import ChatOpenAI
from langchain.memory import ConversationBufferMemory
from langchain.prompts.chat import MessagesPlaceholder
from langchain.schema import SystemMessage
from langchain.tools import StructuredTool
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


class Config(BaseModel.Config):
    arbitrary_types_allowed = True


class FileBot(Bot):
    Config = Config

    llm = ChatOpenAI
    file_path: Path
    cache_path: Path | None
    code_info: pd.DataFrame
    tools: list[StructuredTool]
    executor: AgentExecutor
    get_bot_func: Callable

    @root_validator(pre=True)
    def init_code_info(cls, values: dict) -> dict:
        # TODO: Maybe it's too redundent to have code_info and file_path?
        # Maybe I can have different class methods for init using different parameters
        # For that, I need to reorganize the code_info cache to include file_path
        code_info = values.get("code_info")
        cache_path = values.get("cache_path")
        file_path = values.get("file_path")

        if code_info is not None:
            return values

        if cache_path is not None:
            values["code_info"] = load_cached_codebase_info(cache_path=cache_path)
        else:
            raw_code, code_info_dict = extract_code_info(file_path=file_path)
            values["code_info"] = pd.DataFrame(code_info_dict)
        return values

    @root_validator(pre=True)
    def init_tools(cls, values: dict) -> dict:
        code_info = values.get("code_info")
        file_path = values.get("file_path")
        get_bot_func = values.get("get_bot_func")

        values["tools"] = [
            StructuredTool.from_function(
                func=patch_tool(
                    get_related_functions, code_info=code_info, want="name", n=5
                )
            ),
            StructuredTool.from_function(
                func=patch_tool(get_function_code, code_info=code_info)
            ),
            StructuredTool.from_function(
                func=patch_tool(get_function_summaries, code_info=code_info)
            ),
            StructuredTool.from_function(
                func=patch_tool(
                    ask_function_bot, file_path=file_path, get_bot_func=get_bot_func
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

    def ask(self, inputs: str):
        # REMINDER: This function outputs final response and intermediate steps,
        # maybe I can make use of it.
        self.executor(
            inputs=inputs,
            callbacks=[BotStreamingStdOutCallbackHandler()],
        )
