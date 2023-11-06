# %%
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4

import pygraphviz as pgv
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


from typing import NewType

NodeURI = NewType("NodeURI", URI)
ChartURI = NewType("ChartURI", URI)


class Connection(BaseModel):
    # TODO: Add check for valid connection
    # TODO: need to fix the type annotation BaseFlowchartNode
    node: Any
    label: str = None
    # NOTE: Must add in_edges after adding the subgraph to show clusters
    # correctly. Otherwise the from_node in the edges will be added to the
    # subgraph. Also, start node is unknown at this point.
    graph: pgv.AGraph = None

    class Config:
        arbitrary_types_allowed = True


class Flowchart(BaseModel):
    name: str | None = Field(default=None)
    # TODO: Make uuid_name same with Node's name?
    uuid_name: str
    type: FlowchartType
    start: Any
    out_edges: list[Connection] = Field(default_factory=list)

    @root_validator(pre=True)
    def set_chart_uuid_name(cls, values: dict) -> str:
        name = values.get("name", "no_name")
        values["uuid_name"] = f"{name}_{str(uuid4())}"
        return values


class BaseFlowchartNode(BaseModel, ABC):
    shape: ClassVar[str]
    name: str
    uuid_name: str
    label: str
    # Any node can have a subchart but after reorganizing, only IfNode and
    # LoopNode will have subcharts
    subchart: Flowchart = None
    expand: bool = False

    @property
    def node_attrs(self) -> dict[str, str]:
        # Use this method to customize the visualization of the node
        return dict(
            label=self.label,
            shape=self.shape,
        )

    @root_validator(pre=True)
    def set_uuid_name(cls, values: dict) -> str:
        name = values.get("name", "no_name")
        values["uuid_name"] = f"{name}_{str(uuid4())}"
        return values

    @property
    def type(self) -> str:
        return self.__class__.__name__


class ActionNode(BaseFlowchartNode):
    shape: ClassVar[str] = "box"
    next: BaseFlowchartNode | None = None

    def out_edge(self, graph: pgv.AGraph | None = None) -> Connection | None:
        return Connection(node=self, label="", graph=graph)

    def out_edges(self, graph: pgv.AGraph | None = None) -> list[Connection]:
        return [self.out_edge(graph)]


class DecisionNode(BaseFlowchartNode):
    shape: ClassVar[str] = "diamond"

    true: BaseFlowchartNode | None = None
    false: BaseFlowchartNode | None = None

    def true_out_edge(self, graph: pgv.AGraph | None = None) -> Connection | None:
        return Connection(node=self, label="Yes", graph=graph)

    def false_out_edge(self, graph: pgv.AGraph | None = None) -> Connection | None:
        return Connection(node=self, label="No", graph=graph)

    def out_edges(self, graph: pgv.AGraph | None = None) -> list[Connection]:
        return [self.true_out_edge(graph), self.false_out_edge(graph)]


class LoopNode(BaseFlowchartNode):
    """Node for start a new iteration of a loop."""

    shape: ClassVar[str] = "oval"
    next: BaseFlowchartNode | None = None

    def out_edge(self, graph: pgv.AGraph | None = None) -> Connection | None:
        return Connection(node=self, label="", graph=graph)

    def out_edges(self, graph: pgv.AGraph | None = None) -> list[Connection]:
        return [self.out_edge(graph)]


class ExitNode(BaseFlowchartNode):
    """Exits from the middle of the flowchart."""

    shape: ClassVar[str] = "oval"

    # @property
    # def node_attrs(self) -> dict[str, str]:
    #     return dict(
    #         label="",
    #         shape=self.shape,
    #     )


class StartNode(BaseFlowchartNode):
    """The start of the flowchart."""

    shape: ClassVar[str] = "oval"
    name: str = "flowchart_start"
    label: str = "Start"
    next: BaseFlowchartNode

    def out_edge(self, graph: pgv.AGraph | None = None) -> Connection | None:
        return Connection(node=self, label="", graph=graph)

    def out_edges(self, graph: pgv.AGraph | None = None) -> list[Connection]:
        return [self.out_edge(graph)]


class EndNode(BaseFlowchartNode):
    """The end of the flowchart."""

    shape: ClassVar[str] = "oval"
    name: str = "flowchart_end"
    label: str = "End"


def _log_conversion(process: Process, parent: BaseFlowchartNode) -> None:
    chart_type = (
        f"{parent.subchart.type} (expand={parent.expand})"
        if parent.subchart
        else None
    )
    logger.info(
        f"Converted [{process.index}] {process.name=} to an {parent.type} with {chart_type} subchart."
    )


def process_to_action_node(process: Process) -> ActionNode:
    assert isinstance(process.pattern, ActionPattern)
    node = ActionNode(name=process.name, label=process.pattern.body)
    _log_conversion(process, node)
    return node


def process_to_exit_node(process: Process) -> ExitNode:
    assert isinstance(process.pattern, ExitPattern)
    node = ExitNode(name=process.name, label=process.pattern.body)
    _log_conversion(process, node)
    return node


def process_to_node_with_loop_chart(process: Process) -> ActionNode:
    assert isinstance(process.pattern, LoopPattern)

    # Body node
    body = ActionNode(name=f"{process.name}_body", label=process.pattern.body)

    # Setup node
    setup = LoopNode(
        name=f"{process.name}_setup", label=process.pattern.setup, next=body
    )
    if process.subprocesses:
        body.subchart = processes_to_linear_chart(process, chart_name=body.name)
        # TODO: How to handle the last node is ExitNode?
        body.expand = True

    # Decision node
    decision = DecisionNode(
        name=f"{process.name}_decision", label=process.pattern.decision
    )
    body.next = decision
    decision.false = setup

    # Chart including setup, body, and decision nodes
    subchart = Flowchart(name=process.name, type=FlowchartType.LOOP, start=setup)
    # TODO subchart.out_edges seems not necessary
    # subchart.out_edges.append(decision.true_out_edge)

    # Parent node of the chart
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


def _create_node_with_if_chart(processes: list[Process]) -> ActionNode:
    # Could be if or elif pattern
    if_process = processes.pop()

    # Create the subchart of if_node
    true = ActionNode(name=f"{if_process.name}_true", label=if_process.pattern.true)
    if if_process.subprocesses:
        true.subchart = processes_to_linear_chart(if_process, chart_name=true.name)
        true.expand = True

    decision = DecisionNode(
        name=f"{if_process.name}_decision",
        label=if_process.pattern.decision,
        true=true,
    )
    # TODO: Rethink when remove nesting structure.
    subchart = Flowchart(type=FlowchartType.IF, start=decision)
    # subchart.out_edges.append(true.out_edge)
    # TODO: improve the if_node.label to a summary of if_process + all left processes.

    if _still_has_elif(processes):
        decision.false = _create_node_with_if_chart(processes)
    elif _only_has_else(processes):
        label = processes[-1].pattern.body
        decision.false = ActionNode(name=f"{if_process.name}_false", label=label)
    elif if_process.pattern.false:
        decision.false = ActionNode(
            name=f"{if_process.name}_false",
            label=if_process.pattern.false,
        )
    else:
        logger.warning("The if process doesn't have a false branch.")

    # if decision.false:
    #     subchart.out_edges.append(decision.false.out_edge)

    if_node = ActionNode(
        name=if_process.name,
        label=if_process.explanation,
        subchart=subchart,
        # Expand if there are subprocesses or if-elif-else groups
        expand=len(if_process.subprocesses) > 0 or len(processes) > 0,
    )
    _log_conversion(if_process, if_node)
    return if_node


def processes_to_node_with_if_chart(processes: list[Process]) -> ActionNode:
    """create an ActionNode with a subchart for the if-elif(-else) group."""
    assert isinstance(processes[0].pattern, IfPattern)

    if_process = processes[0]
    if len(processes) > 1:
        # TODO: Make this warning in production
        assert if_process.pattern.false is None

    return _create_node_with_if_chart(list(reversed(processes)))


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
            return process_to_action_node(process)
        elif isinstance(process.pattern, ExitPattern):
            return process_to_exit_node(process)
        elif isinstance(process.pattern, LoopPattern):
            return process_to_node_with_loop_chart(process)  # Placeholder for now
        # For If without elif or else, we will also treat it with the group handler for consistency
        elif isinstance(process.pattern, IfPattern):
            return processes_to_node_with_if_chart(processes)
            # Single If as a group for consistency
    elif _is_if_group(processes):
        return processes_to_node_with_if_chart(processes)


def _is_last_if_or_elif(current: list[list[Process]]) -> bool:
    return current and isinstance(current[-1].pattern, (IfPattern, ElifPattern))


def _is_elif_or_else(process: Process) -> bool:
    return isinstance(process.pattern, (ElifPattern, ElsePattern))


def processes_to_linear_chart(
    parent_process: Process, chart_name: str | None = None
) -> Flowchart:
    processes = parent_process.subprocesses
    if not processes:
        return None
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

    nodes = []
    previous = None
    for group in groups:
        node = process_to_node(group)
        # All nodes at parent level should be ActionNode.
        assert isinstance(
            node, (ExitNode, ActionNode)
        ), f"{type(node)} is not ActionNode."
        nodes.append(node)
        if previous is not None:
            previous.next = node
        previous = node

    assert len(nodes) > 0, "The subprocesses must have at least one node."
    subchart = Flowchart(
        name=chart_name or parent_process.name,
        type=FlowchartType.LINEAR,
        start=nodes[0],
    )
    return subchart


def root_process_to_flowchart(process: Process) -> ActionNode:
    assert process.subprocesses, "The root process must have subprocesses."
    subchart = processes_to_linear_chart(process)

    root = ActionNode(
        name=process.name,
        label=process.explanation,
        subchart=subchart,
        expand=True,
    )
    _log_conversion(process, root)

    start = StartNode(next=root)
    end = EndNode()
    root.next = end
    chart = Flowchart(
        name=f"{process.name}_root", type=FlowchartType.LINEAR, start=start
    )
    return chart


def _add_in_edges(
    current_graph: pgv.AGraph, to_node: str, in_edges: list[Connection]
) -> None:
    if in_edges:
        assert isinstance(in_edges, list)
        for edge in in_edges:
            if edge is None:
                continue
            assert isinstance(edge, Connection)
            # NOTE: We use this way to avoid duplicate edges when there is a
            # loop. But this cannot avoid repeated traversal, so still need to
            # think of a better way. It's mainly from the loop decision.false
            # branch.
            from_node = edge.node.uuid_name
            node_edge = (from_node, to_node)
            graph = edge.graph
            if not graph.has_edge(node_edge):
                graph.add_edge(node_edge, label=edge.label)
            elif graph.get_edge(*node_edge).attr["label"] != edge.label:
                logger.warning(
                    f"""
                    Edge {node_edge} already exists with label {graph.get_edge(node_edge).attr['label']}.
                    Will overwrite with label {edge.label}.
                               """
                )
                graph.add_edge(node_edge, label=edge.label)
            else:
                continue
            logger.debug(
                f"Adding edge\n\t{from_node=}\n\t{to_node=}\n\t{edge.label=}\n\t{graph.name=}"
            )


class FlowchartConfig(BaseModel):
    show_cluster: bool = False
    expand_all: bool = False
    fold_all: bool = False  # Has higher priority than expand_all
    expand_list: list[str] = Field(default_factory=list)


def _is_expand(node: BaseFlowchartNode, config: FlowchartConfig) -> bool:
    if config.fold_all:
        return False
    if node.subchart is None:
        # TODO: Mabye we can add further expand logic here
        return False
    if config.expand_all or node.expand or (node.name in config.expand_list):
        return True
    return False


def node_to_graph(
    node: BaseFlowchartNode,
    graph: pgv.AGraph,
    config: FlowchartConfig,
    in_edges: list[Connection] | None = None,
) -> None:
    if graph is None:
        graph = pgv.AGraph(name=node.uuid_name, directed=True, strict=False)

    if node is None:
        return in_edges

    if graph.has_node(node.uuid_name):
        _add_in_edges(graph, node.uuid_name, in_edges)
        return []

    if _is_expand(node, config):
        # For now all nodes with subcharts are ActionNodes
        # TODO: Use logic block
        assert isinstance(node, ActionNode)
        out_edges = flowchart_to_graph(
            node.subchart, graph, in_edges=in_edges, config=config
        )
        if node.next:
            out_edges = node_to_graph(
                node.next, graph, in_edges=out_edges, config=config
            )
        return out_edges

    # TODO: improve node name logic
    graph.add_node(node.uuid_name, **node.node_attrs)
    logger.debug(
        f"Adding node\n\t{node.uuid_name=}\n\t{node.label=}\n\t{graph.name=}."
    )
    _add_in_edges(graph, node.uuid_name, in_edges)

    if isinstance(node, DecisionNode):
        true_out = node_to_graph(
            node.true, graph, in_edges=[node.true_out_edge(graph)], config=config
        )
        false_out = node_to_graph(
            node.false, graph, in_edges=[node.false_out_edge(graph)], config=config
        )
        out_edges = true_out + false_out
    elif isinstance(node, (ActionNode, StartNode)):
        out_edges = node_to_graph(
            node.next, graph, in_edges=node.out_edges(graph), config=config
        )
    elif isinstance(node, LoopNode):
        # TODO: Maybe we can do something to avoid the repeated traversal
        out_edges = node_to_graph(
            node.next, graph, in_edges=node.out_edges(graph), config=config
        )
    elif isinstance(node, (ExitNode, EndNode)):
        logger.info(f"Encounter an ExitNode {node.name} at this branch.")
        out_edges = []

    return out_edges


def flowchart_to_graph(
    flowchart: Flowchart,
    graph: pgv.AGraph,
    config: FlowchartConfig,
    in_edges: list[Connection] | None = None,
) -> pgv.AGraph:
    subgraph_name = (
        f"cluster_{flowchart.uuid_name}"
        if config.show_cluster
        else flowchart.uuid_name
    )
    with graph.subgraph(name=subgraph_name) as subgraph:
        out_edges = node_to_graph(
            flowchart.start, graph=subgraph, config=config, in_edges=in_edges
        )
    # _add_in_edges(graph, flowchart.start.uuid_name, in_edges)
    for e in out_edges:
        e.graph = graph
    return out_edges


def visualize_nodes_and_save(
    input: Flowchart | BaseFlowchartNode, config: FlowchartConfig | None = None
) -> pgv.AGraph:
    if config is None:
        config = FlowchartConfig(
            show_cluster=True, expand_all=True, fold_all=False, expand_list=[]
        )
    graph = pgv.AGraph(name=input.name, strict=False, directed=True)
    if isinstance(input, Flowchart):
        flowchart_to_graph(input, graph=graph, config=config)
    elif isinstance(input, BaseFlowchartNode):
        node_to_graph(input, graph=graph, config=config)
    else:
        raise ValueError(f"Cannot visualize {type(input)}")
    graph.draw(Path(__file__).parent / f"test/{input.name}.png", prog="dot")
    graph.write(Path(__file__).parent / f"test/{input.name}.dot")
    return graph


if __name__ == "__main__":
    # Creating test cases for the conversion functions

    test_action_process = Process(
        name="ActionProcess",
        explanation="This is an action process",
        pattern=ActionPattern(body="Action Body"),
    )
    test_action_process2 = Process(
        name="ActionProcess2",
        explanation="This is an action process2",
        pattern=ActionPattern(body="Action Body2"),
    )
    converted_action_node = process_to_action_node(test_action_process)
    visualize_nodes_and_save(converted_action_node)
    logger.info("======")

    test_exit_process = Process(
        name="ExitProcess",
        explanation="This is an exit process",
        pattern=ExitPattern(body="Exit Body"),
    )
    converted_exit_node = process_to_exit_node(test_exit_process)
    visualize_nodes_and_save(converted_exit_node)
    logger.info("======")

    test_if_process_no_else = Process(
        name="IfProcess_no_else",
        explanation="This is an if process no else",
        pattern=IfPattern(decision="If Decision", true="If True", false=None),
    )
    converted_if_node_no_else = processes_to_node_with_if_chart(
        [test_if_process_no_else]
    )
    visualize_nodes_and_save(converted_if_node_no_else)
    logger.info("======")

    test_if_process_no_sub = Process(
        name="IfProcess_no_sub",
        explanation="This is an if process no sub",
        pattern=IfPattern(decision="If Decision", true="If True", false="If False"),
    )
    converted_if_node_no_sub = processes_to_node_with_if_chart(
        [test_if_process_no_sub]
    )
    visualize_nodes_and_save(converted_if_node_no_sub)
    logger.info("======")

    test_if_process = Process(
        name="IfProcess",
        explanation="This is an if process",
        pattern=IfPattern(decision="If Decision", true="If True", false="If False"),
        subprocesses=[
            test_action_process,
            test_action_process2,
        ],
    )
    converted_if_node = processes_to_node_with_if_chart([test_if_process])
    visualize_nodes_and_save(converted_if_node)
    logger.info("======")

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
    converted_if_elif_else_node = processes_to_node_with_if_chart(
        test_if_elif_else_processes
    )
    visualize_nodes_and_save(converted_if_elif_else_node)
    logger.info("======")

    test_loop_process = Process(
        name="LoopProcess",
        explanation="This is a loop process",
        pattern=LoopPattern(
            setup="Loop Setup", body="Loop Body", decision="Loop Decision"
        ),
        subprocesses=[
            test_action_process,
            test_action_process2,
        ],
    )
    converted_loop_node = process_to_node_with_loop_chart(test_loop_process)
    visualize_nodes_and_save(converted_loop_node)
    logger.info("======")

    all_test_processes = [
        test_if_process_no_sub,
        test_action_process,
        test_if_process_no_else,
        *test_if_elif_else_processes,
        test_loop_process,
        # test_exit_process,
    ]
    # converted_nodes = processes_to_linear_chart(all_test_processes)
    # logger.info("======")

    parent_process = Process(
        name="ParentProcess",
        explanation="This is a parent process",
        subprocesses=all_test_processes,
    )
    converted_flowchart = root_process_to_flowchart(parent_process)
    visualize_nodes_and_save(converted_flowchart)
    logger.info("======")

    pass

# %%
output_path = Path(
    "/Users/jun/Projects/ichigen-coder/.local/flowcharts/autogpt/app/main/run_auto_gpt"
)
autogpt_process = Process.from_file(output_path / "process_saved.json")
autogpt_chart = root_process_to_flowchart(autogpt_process)
visualize_nodes_and_save(autogpt_chart)
