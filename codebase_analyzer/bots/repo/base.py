"""Main classes for the repo bot."""

from __future__ import annotations

from abc import abstractmethod
from pathlib import Path
from typing import Any, Callable, ClassVar

from langchain.agents import AgentExecutor
from langchain.agents.openai_functions_agent.base import OpenAIFunctionsAgent
from langchain.chat_models import ChatOpenAI
from langchain.memory import ConversationBufferMemory
from langchain.prompts.chat import MessagesPlaceholder
from langchain.schema import SystemMessage
from langchain.tools import StructuredTool
from loguru import logger
from pydantic import BaseModel, Field, root_validator, validator

from codebase_analyzer.bots.callbacks import BotStreamingStdOutCallbackHandler
from codebase_analyzer.bots.executor import AgentExecutorBot, Bot
from codebase_analyzer.bots.repo.prompts import SYSTEM_MESSAGE
from codebase_analyzer.parser.deftree import CodeNode
from codebase_analyzer.parser.uri import URI
from codebase_analyzer.tools.base import switch_bot
from codebase_analyzer.tools.patch import patch_tool


class RepoBot(Bot):
    """A bot managing a repository."""

    llm_model: str = Field(..., description="gpt-3.5-turbo-0613 or gpt-4-0613")
    tools: list[StructuredTool]
    executor: AgentExecutor
    ask_manager: Callable = Field(
        ..., description="The function to send asks to my manager."
    )
    overview_path: Path = Field(..., description="Path to the overview of the repo.")
    uri: URI = Field(..., description="URI of the repo.", alias="uri")

    @staticmethod
    def get_system_message(overview_path: Path) -> str:
        overview_path = overview_path
        return SYSTEM_MESSAGE.format(
            summary=overview_path.read_text(),
        )

    @root_validator(pre=True)
    def init_tools(cls, values: dict) -> dict:
        ask_manager = values.get("ask_manager")
        uri = values.get("uri")

        values["tools"] = [
            StructuredTool.from_function(
                func=patch_tool(switch_bot, ask_manager=ask_manager, ask_by=uri),
                return_direct=True,
            ),
        ]
        return values

    @root_validator(pre=True)
    def init_agent_executor(cls, values: dict) -> dict:
        overview_path = values.get("overview_path")
        tools = values.get("tools")
        llm_model = values.get("llm_model")
        llm = ChatOpenAI(
            temperature=0,
            model=llm_model,
            streaming=True,
            client=None,
        )
        agent = OpenAIFunctionsAgent.from_llm_and_tools(
            llm=llm,
            tools=tools,
            system_message=SystemMessage(
                content=cls.get_system_message(overview_path=overview_path)
            ),
            extra_prompt_messages=[MessagesPlaceholder(variable_name="history")],
        )

        values["executor"] = AgentExecutor.from_agent_and_tools(
            agent=agent,
            tools=tools,
            verbose=True,
            return_intermediate_steps=False,
            memory=ConversationBufferMemory(
                memory_key="history",
                return_messages=True,
                output_key="output",
            ),
        )
        return values

    def ask(self, inputs: str) -> str:
        # REMINDER: This function outputs final response and intermediate steps,
        # maybe I can make use of it.
        results = self.executor(
            inputs=inputs,
            callbacks=[BotStreamingStdOutCallbackHandler()],
        )
        return results["output"]
