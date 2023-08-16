"""Base class for bots."""
from __future__ import annotations

from abc import ABC, abstractmethod
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
from pydantic import BaseModel, Field, root_validator

from codebase_analyzer.bots.callbacks import BotStreamingStdOutCallbackHandler
from codebase_analyzer.parser.deftree import CodeNode


class Bot(ABC, BaseModel):
    @abstractmethod
    def ask(self, *args, **kwargs) -> str:
        pass

    def save_cache(self) -> None:
        # NOTE: Not all bots need to save cache
        pass


class AgentExecutorBot(Bot):
    """A bot built on top of AgentExecutor and OpenAIFunctionsAgent."""

    llm_model: str = Field(..., description="gpt-3.5-turbo-0613 or gpt-4-0613")
    code_node: CodeNode = Field(...)
    summary_sheet: str = Field(
        ..., description="Summaries of all children and calls."
    )
    tools: list[StructuredTool]
    executor: AgentExecutor
    ask_manager: Callable = Field(
        ..., description="The function to send asks to my manager."
    )

    @staticmethod
    @abstractmethod
    def get_system_message(code_node: CodeNode) -> str:
        raise NotImplementedError

    @root_validator(pre=True)
    @abstractmethod
    def init_tools(cls, values: dict) -> dict:
        """Each bot should have its own toolset."""
        raise NotImplementedError

    @root_validator(pre=True)
    def init_agent_executor(cls, values: dict) -> dict:
        code_node = values.get("code_node")
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
                content=cls.get_system_message(code_node=code_node)
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

    @property
    def uri(self) -> str:
        return self.code_node.uri

    def ask(self, inputs: str) -> str:
        # REMINDER: This function outputs final response and intermediate steps,
        # maybe I can make use of it.
        results = self.executor(
            inputs=inputs,
            callbacks=[BotStreamingStdOutCallbackHandler()],
        )
        return results["output"]
