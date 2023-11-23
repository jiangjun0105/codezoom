# %%
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import ClassVar, Type, Union

from loguru import logger
from pydantic import BaseModel, Field, root_validator

# %%


class Pattern(BaseModel):
    @property
    def name(self) -> str:
        return self.__class__.__name__

    @classmethod
    def get_name(cls) -> str:
        return cls.__name__

    @classmethod
    def load_saved_dict(cls, obj: dict) -> Pattern:
        type_ = obj.get("type")

        # TODO: Use a better way instead of loop
        for sub_cls in cls.__subclasses__():
            if type_ == sub_cls.get_name():
                return sub_cls.parse_obj(obj)
        raise ValueError(f"Cannot find the pattern type {type_}")


# %%


class LoopPattern(Pattern):
    """Use this function when the outmost process is a loop, e.g. for/while loop."""

    setup: str = Field(
        ...,
        description="The label of setup node which prepares any variables, data structures, or conditions that are required before entering the loop body.",
    )
    body: str = Field(
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


# %%
ROOT_PROCESS_INDEX = ""


class Process(BaseModel):
    name: str
    index: str = ""
    explanation: str
    subprocesses: list[Process] = Field(default_factory=list)
    code_lineno: list[int] = Field(default_factory=list)
    code: str | None = None
    pattern: Pattern = Field(
        default=None
    )  # Union[tuple(Pattern.__subclasses__())] = None

    @property
    def node_name(self):
        return f"{self.index}_{self.name}"

    @property
    def node_shape(self):
        return "diamond" if self.pattern in ["if", "elif"] else "box"

    @classmethod
    def from_file(cls, json_file: Path) -> Process:
        data = json.loads(json_file.read_text())
        return cls.load_saved_dict(data)

    @classmethod
    def load_saved_dict(cls, data: dict) -> Process:
        pattern_dict = data.pop("pattern", None)
        sub_dicts = data.pop("subprocesses", [])
        process = cls.parse_obj(data)
        if pattern_dict is not None:
            process.pattern = Pattern.load_saved_dict(pattern_dict)
        for sub_dict in sub_dicts:
            process.subprocesses.append(cls.load_saved_dict(sub_dict))
        return process

    def to_file(self, json_file: Path, indent: int = 4) -> None:
        data = self.save_to_dict()
        json_file.write_text(json.dumps(data, indent=indent))

    def save_to_dict(self) -> dict:
        process_dict = self.dict()
        self._update_pattern_dict(self, process_dict)
        return process_dict

    def _update_pattern_dict(self, process_obj: Process, process_dict: dict) -> None:
        if process_obj.pattern is not None:
            process_dict["pattern"]["type"] = process_obj.pattern.get_name()

        for sub_obj, sub_dict in zip(
            process_obj.subprocesses, process_dict["subprocesses"]
        ):
            self._update_pattern_dict(sub_obj, sub_dict)
        return process_dict


# %%
if __name__ == "__main__":
    # if True:

    test_action_process = Process(
        name="ActionProcess",
        explanation="This is an action process",
        pattern=ActionPattern(body="Action Body"),
    )
    test_exit_process = Process(
        name="ExitProcess",
        explanation="This is an exit process",
        pattern=ExitPattern(body="Exit Body"),
    )
    test_loop_process = Process(
        name="LoopProcess",
        explanation="This is a loop process",
        pattern=LoopPattern(
            setup="Loop Setup", body="Loop Body", decision="Loop Decision"
        ),
        subprocesses=[
            test_action_process,
        ],
    )
    test_if_elif_else_processes = [
        Process(
            name="IfProcess_with_elif_else",
            explanation="This is the main if process",
            pattern=IfPattern(decision="If Decision", true="If True"),
        ),
        Process(
            name="ElifProcess1",
            explanation="This is an elif process1",
            pattern=ElifPattern(decision="Elif Decision1", true="Elif Body"),
        ),
        Process(
            name="ElifProcess2",
            explanation="This is an elif process2",
            pattern=ElifPattern(decision="Elif Decision2", true="Elif Body"),
        ),
        Process(
            name="ElseProcess",
            explanation="This is an else process",
            pattern=ElsePattern(body="Else Body"),
        ),
    ]
    all_test_processes = [
        test_action_process,
        *test_if_elif_else_processes,
        test_loop_process,
        test_exit_process,
    ]
    parent_process = Process(
        name="ParentProcess",
        explanation="This is a parent process",
        subprocesses=all_test_processes,
    )
    import copy

    before_save = copy.deepcopy(parent_process)
    d1 = parent_process.save_to_dict()
    json_file = Path(__file__).parent / "test.json"
    parent_process.to_file(json_file, indent=4)
    print(json.dumps(d1, indent=4))
    loaded = Process.load_saved_dict(d1)
    loaded2 = Process.from_file(json_file)
    print(json.dumps(loaded.dict(), indent=4))
    assert before_save == parent_process
    assert loaded == parent_process
    assert loaded2 == parent_process
    pass
    # new_process = Process.parse_obj(d)
    # assert new_process == parent_process
# %%
