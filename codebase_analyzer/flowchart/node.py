# %%
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from loguru import logger
from pydantic import BaseModel, Field, root_validator

from codebase_analyzer.flowchart.datamodel import (
    ActionPattern,
    ElifPattern,
    ElsePattern,
    ExitPattern,
    IfPattern,
    LoopPattern,
    Pattern,
    Process,
)
from codebase_analyzer.parser.uri import URI, uri_stem

REPO_ROOT = Path(__file__).parent.parent.parent
CACHE_ROOT = REPO_ROOT / "shared_cache"
LOCAL_ROOT = REPO_ROOT / ".local"

# Convert Process to Nodes
# decide patterns of each node
# Convert the node type to the decided pattern
from abc import ABC


class FlowchartType(Enum):
    IF: str = "IF"
    LOOP: str = "LOOP"
    LINEAR: str = "LINEAR"


class Flowchart(BaseModel):
    type: FlowchartType
    start: Any
    # This will share the same object as the end node, but it's fine
    end: Any
    # out_edges: list[Connection] = Field(default_factory=list)


class BaseFlowchartNode(BaseModel, ABC):
    shape: ClassVar[str]
    name: str
    label: str
    # Any node can have a subchart but after reorganizing, only IfNode and
    # LoopNode will have subcharts
    subchart: Flowchart = None
    expand: bool = False

    @property
    def node_attrs(self) -> dict[str, str]:
        # Use this method to customize the visualization of the node
        return dict(
            name=self.name,
            label=self.label,
            shape=self.shape,
        )

    @property
    def type(self) -> str:
        return self.__class__.__name__


class Connection(BaseModel):
    node: BaseFlowchartNode
    label: str = None


class ActionNode(BaseFlowchartNode):
    shape: ClassVar[str] = "box"
    next: BaseFlowchartNode | None = None


class DecisionNode(BaseFlowchartNode):
    shape: ClassVar[str] = "diamond"
    # NOTE: Add edge labels when converting to graphviz
    true: BaseFlowchartNode | None = None
    false: BaseFlowchartNode | None = None


class LoopNode(BaseFlowchartNode):
    shape: ClassVar[str] = "oval"
    next: BaseFlowchartNode | None = None


class ExitNode(BaseFlowchartNode):
    shape: ClassVar[str] = "doublecircle"


def _log_conversion(process: Process, parent: BaseFlowchartNode) -> None:
    chart_type = (
        f"{parent.subchart.type} (expand={parent.expand})"
        if parent.subchart
        else None
    )
    logger.info(
        f"Converted [{process.index}] {process.name=} to an {parent.type} with {chart_type} subchart."
    )


def convert_action_pattern(process: Process) -> ActionNode:
    assert isinstance(process.pattern, ActionPattern)
    node = ActionNode(name=process.name, label=process.pattern.body)
    _log_conversion(process, node)
    return node


def convert_exit_pattern(process: Process) -> ExitNode:
    assert isinstance(process.pattern, ExitPattern)
    node = ExitNode(name=process.name, label=process.pattern.body)
    _log_conversion(process, node)
    return node


def convert_loop_pattern(process: Process) -> ActionNode:
    assert isinstance(process.pattern, LoopPattern)

    setup = LoopNode(name=f"{process.name}_setup", label=process.pattern.setup)
    # TODO: add body nodes recursively after process supports nested processes
    body = ActionNode(name=f"{process.name}_body", label=process.pattern.body)
    if process.subprocesses:
        nodes = convert_process_groups(process.subprocesses)
        body.subchart = Flowchart(type=FlowchartType.LINEAR, start=nodes[0])
        body.expand = True

    decision = DecisionNode(
        name=f"{process.name}_decision", label=process.pattern.decision, true=body
    )
    subchart = Flowchart(type=FlowchartType.LOOP, start=setup)
    subchart.end = ExitNode(name=f"{process.name}_chart_end", label="End")

    setup.next = body
    body.next = decision
    decision.false = setup
    decision.true = subchart.end

    parent = ActionNode(
        name=process.name,
        label=process.explanation,
        subchart=subchart,
        expand=len(process.subprocesses) > 0,
    )
    _log_conversion(process, parent)
    return parent


def _still_has_elif(processes: list[Process]) -> bool:
    # NOTE: The list is reversed
    return len(processes) >= 1 and isinstance(processes[-1].pattern, ElifPattern)


def _only_has_else(processes: list[Process]) -> bool:
    # NOTE: The list is reversed
    return len(processes) == 1 and isinstance(processes[0].pattern, ElsePattern)


def _create_if_node(processes: list[Process]) -> ActionNode:
    # Could be if or elif pattern
    if_process = processes.pop()

    # Create the subchart of if_node
    true = ActionNode(name=f"{if_process.name}_true", label=if_process.pattern.true)
    if if_process.subprocesses:
        nodes = convert_process_groups(if_process.subprocesses)
        true.subchart = Flowchart(type=FlowchartType.LINEAR, start=nodes[0])
        true.expand = True

    decision = DecisionNode(
        name=f"{if_process.name}_decision",
        label=if_process.pattern.decision,
        true=true,
    )
    # TODO: Rethink when remove nesting structure.
    subchart = Flowchart(type=FlowchartType.IF, start=decision)
    subchart.end = ExitNode(name=f"{if_process.name}_chart_end", label="End")
    true.next = subchart.end
    # TODO: improve the if_node.label to a summary of if_process + all left processes.

    if _still_has_elif(processes):
        decision.false = _create_if_node(processes)
        decision.false.next = subchart.end
    elif _only_has_else(processes):
        label = processes[-1].pattern.body
        decision.false = ActionNode(
            name=f"{if_process.name}_false", label=label, next=subchart.end
        )
    elif if_process.pattern.false:
        decision.false = ActionNode(
            name=f"{if_process.name}_false",
            label=if_process.pattern.false,
            next=subchart.end,
        )
    else:
        decision.false = subchart.end

    if_node = ActionNode(
        name=if_process.name,
        label=if_process.explanation,
        subchart=subchart,
        # Expand if there are subprocesses or if-elif-else groups
        expand=len(if_process.subprocesses) > 0 or len(processes) > 0,
    )
    _log_conversion(if_process, if_node)
    return if_node


def convert_if_group(processes: list[Process]) -> ActionNode:
    """create an ActionNode with a subchart for the if-elif(-else) group."""
    assert isinstance(processes[0].pattern, IfPattern)

    if_process = processes[0]
    if len(processes) > 1:
        # TODO: Make this warning in production
        assert if_process.pattern.false is None

    return _create_if_node(list(reversed(processes)))


def _is_if_group(processes: list[Process]) -> bool:
    # Multiple processes mean we have an if-elif(-else) group
    # For now we only have if-elif-else groups
    # Later we might have linear groups as well
    assert len(processes) > 1
    if not isinstance(processes[0].pattern, IfPattern):
        raise ValueError("The first process must be an IfPattern")
    if not isinstance(processes[-1].pattern, (ElifPattern, ElsePattern)):
        raise ValueError("The last process must be an ElifPattern or ElsePattern")
    if any(not isinstance(p.pattern, ElifPattern) for p in processes[1:-1]):
        raise ValueError("The middle processes must be ElifPattern")
    return True


def process_to_node(processes: list[Process]) -> BaseFlowchartNode:

    if len(processes) == 1:
        process = processes[0]
        if isinstance(process.pattern, ActionPattern):
            return convert_action_pattern(process)
        elif isinstance(process.pattern, ExitPattern):
            return convert_exit_pattern(process)
        elif isinstance(process.pattern, LoopPattern):
            return convert_loop_pattern(process)  # Placeholder for now
        # For If without elif or else, we will also treat it with the group handler for consistency
        elif isinstance(process.pattern, IfPattern):
            return convert_if_group(processes)
            # Single If as a group for consistency
    elif _is_if_group(processes):
        return convert_if_group(processes)


def _is_last_if_or_elif(current: list[list[Process]]) -> bool:
    return current and isinstance(current[-1].pattern, (IfPattern, ElifPattern))


def _is_elif_or_else(process: Process) -> bool:
    return isinstance(process.pattern, (ElifPattern, ElsePattern))


def convert_process_groups(processes: list[Process]) -> list[BaseFlowchartNode]:
    groups: list[list[Process]] = []  # list of lists to keep track of process groups
    current: list[Process] = []  # Current group being built

    for process in processes:
        if isinstance(process.pattern, IfPattern):
            # Start a new group with the current if process
            current = [process]
            groups.append(current)
        elif _is_elif_or_else(process) and _is_last_if_or_elif(current):
            current.append(process)
        else:
            current = [process]
            groups.append(current)

    converted_nodes = []
    start = None
    for group in groups:
        node = process_to_node(group)
        # All nodes at parent level should be ActionNode.
        assert isinstance(
            node, (ExitNode, ActionNode)
        ), f"{type(node)} is not ActionNode."
        converted_nodes.extend(node)
        if start is not None:
            start.next = node
        start = node

    return converted_nodes


def root_process_to_flowchart(process: Process) -> ActionNode:
    assert process.subprocesses, "The root process must have subprocesses."
    nodes = convert_process_groups(process.subprocesses)
    assert len(nodes) > 0, "The subprocesses must have at least one node."

    parent = ActionNode(
        name=process.name,
        label=process.explanation,
        subchart=Flowchart(type=FlowchartType.LINEAR, start=nodes[0]),
        expand=True,
    )
    _log_conversion(process, parent)
    return parent


if __name__ == "__main__":
    # Creating test cases for the conversion functions

    test_action_process = Process(
        name="ActionProcess",
        explanation="This is an action process",
        pattern=ActionPattern(body="Action Body"),
    )
    converted_action_node = convert_action_pattern(test_action_process)
    logger.info("======")

    test_exit_process = Process(
        name="ExitProcess",
        explanation="This is an exit process",
        pattern=ExitPattern(body="Exit Body"),
    )
    converted_exit_node = convert_exit_pattern(test_exit_process)
    logger.info("======")

    test_if_process_no_sub = Process(
        name="IfProcess_no_sub",
        explanation="This is an if process no sub",
        pattern=IfPattern(decision="If Decision", true="If True", false="If False"),
    )
    converted_if_node = convert_if_group([test_if_process_no_sub])
    logger.info("======")

    test_if_process = Process(
        name="IfProcess",
        explanation="This is an if process",
        pattern=IfPattern(decision="If Decision", true="If True", false="If False"),
        subprocesses=[
            test_action_process,
            test_exit_process,
        ],
    )
    converted_if_node = convert_if_group([test_if_process])
    logger.info("======")

    test_if_elif_else_processes = [
        Process(
            name="IfProcess",
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
    converted_if_elif_else_node = convert_if_group(test_if_elif_else_processes)
    logger.info("======")

    test_loop_process = Process(
        name="LoopProcess",
        explanation="This is a loop process",
        pattern=LoopPattern(
            setup="Loop Setup", body="Loop Body", decision="Loop Decision"
        ),
        subprocesses=[
            test_action_process,
            test_exit_process,
        ],
    )
    converted_loop_node = convert_loop_pattern(test_loop_process)
    logger.info("======")

    all_test_processes = [
        test_action_process,
        test_if_process,
        *test_if_elif_else_processes,
        test_loop_process,
        test_exit_process,
    ]
    converted_nodes = convert_process_groups(all_test_processes)
    logger.info("======")

    parent_process = Process(
        name="ParentProcess",
        explanation="This is a parent process",
        subprocesses=all_test_processes,
    )
    converted_flowchart = root_process_to_flowchart(parent_process)
    logger.info("======")

    pass
