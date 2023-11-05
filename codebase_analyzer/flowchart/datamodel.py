from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import ClassVar

import pandas as pd
from langchain.chains import LLMChain
from langchain.chat_models import ChatOpenAI
from langchain.prompts import (
    AIMessagePromptTemplate,
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain.schema import AIMessage, BaseMessage, HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel, Field, root_validator

from codebase_analyzer.bots.callbacks import BotStreamingStdOutCallbackHandler
from codebase_analyzer.flowchart.utils import _output_path
from codebase_analyzer.parser.codeinfo import check_state, update_state
from codebase_analyzer.parser.deftree import CodeInfo, CodeNode
from codebase_analyzer.parser.uri import URI, uri_stem


class Pattern(BaseModel):
    @property
    def name(self) -> str:
        return self.__class__.__name__

    @classmethod
    def get_name(cls) -> str:
        return cls.__name__


class LoopPattern(Pattern):
    """Use this function when the outmost process is a loop, e.g. for/while loop."""

    setup: str = Field(
        ...,
        description="The label of setup node which prepares any variables, data structures, or conditions that are required before entering the loop body.",
    )
    body: str = Field(
        default=None,
        description="The label of body node, which is the main part of the loop where the repeated actions take place.",
    )
    decision: str = Field(
        ...,
        description="The label of termination check node, which is to determine whether the loop should continue iterating or terminate.",
    )


class IfPattern(Pattern):
    """Use this tool when the outmost process is a if/switch condition."""

    decision: str = Field(
        ...,
        description="The label of the node to determine whether the condition is met.",
    )
    true: str = Field(
        ...,
        description="The label of node which will be executed when the condition is met.",
    )
    false: str | None = Field(
        default=None,
        description="The label of node which will be executed when the condition is not met.",
    )


class ElifPattern(Pattern):
    """Use this tool when the outmost process is a `elif` logic."""

    decision: str = Field(
        ...,
        description="The label of the node to determine whether the condition is met.",
    )
    true: str = Field(
        ..., description="The label of process if the condition is met."
    )
    false: ClassVar[None] = None


class ElsePattern(Pattern):
    """Use this tool when the outmost process is a `else` logic."""

    body: str = Field(..., description="The label of node for body process.")


class ActionPattern(Pattern):
    """Use this tool when the outmost process is not if/elif/else/loop."""

    body: str = Field(
        ..., description="The refined label of the process shown in the flowchart."
    )


class ExitPattern(Pattern):
    """Use this tool when this step will exit the program."""

    body: str = Field(
        ..., description="The refined label of the process shown in the flowchart."
    )


class Process(BaseModel):
    name: str
    index: str = ""
    explanation: str
    subprocesses: list[Process] = Field(default_factory=list)
    code_lineno: list[int] = Field(default_factory=list)
    code: str | None = None
    pattern: Pattern = None

    @classmethod
    def from_file(cls, process_json_file: Path) -> Process:
        with open(process_json_file, "r") as f:
            process_json = json.load(f)
        return cls.parse_obj(process_json)

    @property
    def node_name(self):
        return f"{self.index}_{self.name}"

    @property
    def node_shape(self):
        return "diamond" if self.pattern in ["if", "elif"] else "box"
